from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import math
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core.runtime import InstanceRuntimeManager
from instances.models import InstanceConfig
from storage.settings import AppSettingsStore


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _html_response(handler: BaseHTTPRequestHandler, status: int, html: str):
    raw = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _redirect_response(handler: BaseHTTPRequestHandler, location: str):
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


class HubHttpServer:
    def __init__(self, host: str, port: int, runtime: InstanceRuntimeManager, settings: AppSettingsStore):
        self.host = host
        self.port = port
        self.runtime = runtime
        self.settings = settings
        self.httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._procs: dict[str, subprocess.Popen] = {}
        self._proc_lock = threading.Lock()

    @staticmethod
    def _url_online(url: str, timeout: float = 1.2) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout):
                return True
        except Exception:
            return False

    @staticmethod
    def _system_python_cmd() -> list[str]:
        if shutil.which("py"):
            return ["py", "-3"]
        if shutil.which("python"):
            return ["python"]
        return [sys.executable]

    @staticmethod
    def _python_cmd(app_dir: str) -> str:
        app_path = Path(app_dir)
        venv_python = app_path / ".venv" / "Scripts" / "python.exe"
        return str(venv_python) if venv_python.exists() else sys.executable

    def _ensure_backend_runtime(self, app_dir: str) -> bool:
        app_path = Path(app_dir)
        if not app_path.exists():
            return False

        venv_python = app_path / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            cmd = self._system_python_cmd() + ["-m", "venv", ".venv"]
            proc = subprocess.run(cmd, cwd=str(app_path), text=True, capture_output=True, check=False)
            if proc.returncode != 0:
                out = (proc.stderr or proc.stdout or "").strip()
                print(f"[Runtime] Falha ao criar venv em {app_path}: {out}")
                return False

        req_file = app_path / "requirements.txt"
        marker = app_path / ".venv" / ".deps_ok"
        must_install = False
        if req_file.exists():
            if not marker.exists():
                must_install = True
            else:
                try:
                    must_install = marker.stat().st_mtime < req_file.stat().st_mtime
                except Exception:
                    must_install = True

        if must_install:
            pip_up = subprocess.run(
                [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
                cwd=str(app_path),
                text=True,
                capture_output=True,
                check=False,
            )
            if pip_up.returncode != 0:
                out = (pip_up.stderr or pip_up.stdout or "").strip()
                print(f"[Runtime] Falha ao atualizar pip em {app_path}: {out}")
                return False

            pip_req = subprocess.run(
                [str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=str(app_path),
                text=True,
                capture_output=True,
                check=False,
            )
            if pip_req.returncode != 0:
                out = (pip_req.stderr or pip_req.stdout or "").strip()
                print(f"[Runtime] Falha ao instalar requisitos em {app_path}: {out}")
                return False
            try:
                marker.write_text("ok", encoding="utf-8")
            except Exception:
                pass
            print(f"[Runtime] Dependencias preparadas para {app_path}")

        return True

    def _start_app_if_needed(self, key: str, app_dir: str, args: list[str]) -> bool:
        with self._proc_lock:
            proc = self._procs.get(key)
            if proc is not None and proc.poll() is None:
                return True
            try:
                if not self._ensure_backend_runtime(app_dir):
                    return False
                cmd = [self._python_cmd(app_dir)] + list(args or ["main.py"])
                self._procs[key] = subprocess.Popen(
                    cmd,
                    cwd=app_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                return False

    def _clone_if_needed(self, inst: InstanceConfig) -> bool:
        app_path = Path(str(inst.app_dir or ""))
        if app_path.exists():
            return True
        if not inst.auto_clone_missing:
            return False
        if not inst.repo_url:
            return False
        if shutil.which("git") is None:
            return False
        try:
            app_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--branch", inst.repo_branch or "main", inst.repo_url, str(app_path)]
            proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
            if proc.returncode != 0:
                out = (proc.stderr or proc.stdout or "").strip()
                print(f"[Clone] Falha em {inst.display_name}: {out}")
                return False
            print(f"[Clone] Repositorio clonado para {app_path}")
            return True
        except Exception as exc:
            print(f"[Clone] Erro ao clonar {inst.display_name}: {exc}")
            return False

    def _ensure_backend_online(self, inst: InstanceConfig) -> bool:
        if self._url_online(inst.backend_url):
            return True
        if not inst.app_dir:
            return False
        if not self._clone_if_needed(inst):
            # se a pasta ja existir mas clone nao era necessario, segue normalmente
            if not Path(inst.app_dir).exists():
                return False
        if not self._start_app_if_needed(inst.instance_id, inst.app_dir, inst.start_args):
            return False
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._url_online(inst.backend_url):
                return True
            time.sleep(0.6)
        return False

    @staticmethod
    def _backend_target(base_url: str, inbound_path: str, prefix: str) -> str:
        # inbound_path ex: /financeiro/api/history?limit=300 -> /api/history?limit=300
        parsed_in = urlparse(inbound_path)
        path = parsed_in.path[len(prefix) :]
        if not path.startswith("/"):
            path = "/" + path
        parsed = urlparse(base_url)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", parsed_in.query or "", ""))

    @staticmethod
    def _rewrite_location_for_prefix(location: str, prefix: str) -> str:
        parsed = urlparse(location or "")
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        base = f"/{prefix}"
        if not (path == base or path.startswith(f"{base}/")):
            path = f"{base}{path}"
        return urllib.parse.urlunparse(("", "", path, "", parsed.query or "", parsed.fragment or ""))

    @staticmethod
    def _rewrite_text_for_prefix(body: bytes, content_type: str, prefix: str) -> bytes:
        ctype = (content_type or "").lower()
        if "text/html" not in ctype and "javascript" not in ctype:
            return body
        try:
            text = body.decode("utf-8", errors="ignore")
        except Exception:
            return body

        # API and auth routes
        text = text.replace('"/api/', f'"/{prefix}/api/')
        text = text.replace("'/api/", f"'/{prefix}/api/")
        text = text.replace("`/api/", f"`/{prefix}/api/")
        text = text.replace('fetch("/api/', f'fetch("/{prefix}/api/')
        text = text.replace("fetch('/api/", f"fetch('/{prefix}/api/")
        text = text.replace("fetch(`/api/", f"fetch(`/{prefix}/api/")

        text = text.replace('href="/logout"', f'href="/{prefix}/logout"')
        text = text.replace('href="/login"', f'href="/{prefix}/login"')
        text = text.replace('action="/login"', f'action="/{prefix}/login"')
        text = text.replace('action="/logout"', f'action="/{prefix}/logout"')

        # JS redirects in FinanceBot pages
        text = text.replace("window.location.href='/'", f"window.location.href='/{prefix}/'")
        text = text.replace('window.location.href="/"', f'window.location.href="/{prefix}/"')
        text = text.replace("window.location='/'", f"window.location='/{prefix}/'")
        text = text.replace('window.location="/"', f'window.location="/{prefix}/"')
        text = text.replace("window.location.href='/login'", f"window.location.href='/{prefix}/login'")
        text = text.replace('window.location.href="/login"', f'window.location.href="/{prefix}/login"')
        text = text.replace("window.location='/login'", f"window.location='/{prefix}/login'")
        text = text.replace('window.location="/login"', f'window.location="/{prefix}/login"')

        # Static/media routes commonly used by FinanceBot UI
        root_paths = [
            "/store-image",
            "/favicon.ico",
            "/assets/",
            "/static/",
        ]
        for p in root_paths:
            text = text.replace(f'"{p}', f'"/{prefix}{p}')
            text = text.replace(f"'{p}", f"'/{prefix}{p}")
            text = text.replace(f"url({p}", f"url(/{prefix}{p}")
            text = text.replace(f'url("{p}', f'url("/{prefix}{p}')
            text = text.replace(f"url('{p}", f"url('/{prefix}{p}")

        return text.encode("utf-8")

    def _proxy(self, handler: BaseHTTPRequestHandler, inst: InstanceConfig):
        prefix = inst.route_prefix.strip("/")
        prefix_path = f"/{prefix}"
        target = self._backend_target(inst.backend_url, handler.path, prefix_path)

        headers = {}
        for k, v in handler.headers.items():
            kl = k.lower()
            if kl in {"host", "content-length", "accept-encoding", "connection"}:
                continue
            headers[k] = v

        body = b""
        if handler.command in {"POST", "PUT", "PATCH"}:
            try:
                size = int(handler.headers.get("Content-Length", "0"))
            except Exception:
                size = 0
            if size > 0:
                body = handler.rfile.read(size)

        req = urllib.request.Request(target, data=body if body else None, headers=headers, method=handler.command)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                ct = resp.headers.get("Content-Type", "")
                raw = self._rewrite_text_for_prefix(raw, ct, prefix)

                handler.send_response(resp.status)
                for k, v in resp.headers.items():
                    kl = k.lower()
                    if kl in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                        continue
                    if kl == "location":
                        handler.send_header("Location", self._rewrite_location_for_prefix(v, prefix))
                        continue
                    handler.send_header(k, v)
                handler.send_header("Content-Length", str(len(raw)))
                handler.end_headers()
                handler.wfile.write(raw)
                return
        except urllib.error.HTTPError as e:
            raw = e.read()
            ct = e.headers.get("Content-Type", "")
            raw = self._rewrite_text_for_prefix(raw, ct, prefix)
            handler.send_response(e.code)
            for k, v in e.headers.items():
                kl = k.lower()
                if kl in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                    continue
                if kl == "location":
                    handler.send_header("Location", self._rewrite_location_for_prefix(v, prefix))
                    continue
                handler.send_header(k, v)
            handler.send_header("Content-Length", str(len(raw)))
            handler.end_headers()
            handler.wfile.write(raw)
            return
        except Exception as exc:
            _html_response(handler, 502, f"<h1>Backend indisponivel</h1><p>{exc}</p>")

    def warm_up_enabled_backends(self) -> None:
        cfg = self.settings.load()
        for inst in cfg.instances:
            if not inst.enabled:
                continue
            ok = self._ensure_backend_online(inst)
            print(f"[Warmup] {inst.display_name}: {'OK' if ok else 'FALHA'}")

    @staticmethod
    def _instances_by_prefix(instances: list[InstanceConfig]) -> dict[str, InstanceConfig]:
        out: dict[str, InstanceConfig] = {}
        for inst in instances:
            p = inst.route_prefix.strip("/")
            if p and p not in out:
                out[p] = inst
        return out

    def start(self) -> None:
        runtime = self.runtime
        settings_store = self.settings

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _route(self):
                cfg = settings_store.load()
                path = urlparse(self.path).path
                by_prefix = self.server.hub_ref._instances_by_prefix(cfg.instances)

                if path == "/":
                    return _html_response(self, 200, _render_home_html(cfg.instances))

                if path == "/hub/api/instances":
                    return _json_response(self, 200, {"items": runtime.list()})

                for prefix, inst in by_prefix.items():
                    base = f"/{prefix}"
                    if path == base:
                        return _redirect_response(self, f"{base}/")
                    if path.startswith(f"{base}/"):
                        ok = self.server.hub_ref._ensure_backend_online(inst)
                        if not ok:
                            return _html_response(
                                self,
                                503,
                                f"<h1>{inst.display_name} indisponivel</h1>"
                                "<p>Nao foi possivel iniciar ou alcancar o backend configurado</p>",
                            )
                        return self.server.hub_ref._proxy(self, inst)

                return _json_response(self, 404, {"ok": False, "error": "Nao encontrado"})

            def do_GET(self):
                return self._route()

            def do_POST(self):
                return self._route()

            def do_PUT(self):
                return self._route()

            def do_PATCH(self):
                return self._route()

            def do_DELETE(self):
                return self._route()

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.hub_ref = self
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="hub-http")
        self._thread.start()

    def join_forever(self):
        if self._thread:
            self._thread.join()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        with self._proc_lock:
            for proc in self._procs.values():
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            self._procs.clear()


def _base_styles() -> str:
    return """
    @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;600;700;900&display=swap');
    :root{--bg:#eff0f2;--ink:#131313;--hub:#176fe5;--hub-center:#9cdaf8}
    body{font-family:'Lexend',sans-serif;background:var(--bg);margin:0;padding:16px;color:var(--ink)}
    *{font-family:'Lexend',sans-serif}
    .container{max-width:900px;margin:0 auto;text-align:center}
    .title-wrap{display:inline-block;position:relative;margin-top:4px}
    .title-wrap::after{content:"";position:absolute;left:-8px;right:-8px;height:14px;bottom:6px;background:#c8f1ff;z-index:0}
    .title{position:relative;z-index:1;font-size:58px;font-weight:900;line-height:1;margin:0}
    .hub-wrap{display:flex;justify-content:center;align-items:center;margin-top:8px}
    .hub-diagram{position:relative;width:740px;height:740px;max-width:96vw;max-height:96vw}
    .node{position:absolute;left:50%;top:50%;transform:translate(calc(-50% + var(--x)), calc(-50% + var(--y)));display:flex;align-items:center;justify-content:center;text-decoration:none;color:#232323}
    .spoke{width:132px;height:132px;border-radius:999px;background:#fff;border:7px solid var(--c);font-size:0;box-sizing:border-box;padding:14px;text-align:center}
    .spoke-label{font-size:18px;font-weight:700;line-height:1.08;display:flex;align-items:center;justify-content:center;flex-direction:column;min-height:100%;text-align:center}
    .connector{position:absolute;left:50%;top:50%;width:5px;height:122px;background:var(--c);transform:translate(-50%,-50%) rotate(var(--a)) translateY(-190px);transform-origin:center}
    .hub-shell{position:absolute;left:50%;top:50%;width:252px;height:252px;border-radius:999px;transform:translate(-50%,-50%);background:conic-gradient(#5f87d9 0 60deg,#45c3ac 60deg 120deg,#b6d45b 120deg 180deg,#f2ac73 180deg 240deg,#ba8fe8 240deg 300deg,#5f87d9 300deg 360deg)}
    .hub-core{position:absolute;left:50%;top:50%;width:236px;height:236px;border-radius:999px;transform:translate(-50%,-50%);background:var(--hub);display:flex;align-items:center;justify-content:center}
    .hub-center{width:116px;height:116px;border-radius:999px;background:var(--hub-center);display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:700;font-size:38px;line-height:1.02;color:#0f172a}
    .hub-center small{font-size:16px;font-weight:700}
    .hub-label-top{position:absolute;left:50%;top:66px;transform:translateX(-50%) rotate(-11deg);color:#fff;font-size:31px;font-weight:700;line-height:1}
    .hub-label-bottom{position:absolute;left:50%;bottom:56px;transform:translateX(-50%);color:#fff;font-size:34px;font-weight:700;line-height:1}
    @media (max-width:760px){
      .title{font-size:44px}
      .spoke{width:106px;height:106px;border-width:6px;padding:10px}
      .spoke-label{font-size:16px}
      .connector{height:95px;transform:translate(-50%,-50%) rotate(var(--a)) translateY(-152px)}
      .hub-shell{width:206px;height:206px}
      .hub-core{width:192px;height:192px}
      .hub-center{width:92px;height:92px;font-size:30px}
      .hub-center small{font-size:12px}
      .hub-label-top{top:52px;font-size:24px}
      .hub-label-bottom{bottom:44px;font-size:24px}
    }
    """


def _render_home_html(instances: list[InstanceConfig]) -> str:
    colors = ["#e08dc8", "#45c2ad", "#b4d15a", "#f1ad77", "#b98be2", "#5e8ad8"]
    slot_angles = [-90, -30, 30, 90, 150, 210]
    # fill to 6 spokes with placeholders for future modules
    padded = list(instances[:6])
    while len(padded) < 6:
        padded.append(
            InstanceConfig(
                instance_id=f"placeholder_{len(padded)}",
                display_name="Spoke page",
                instance_type="module",
                enabled=False,
                route_prefix="",
            )
        )

    spokes = []
    radius = 252
    for i, inst in enumerate(padded):
        angle_deg = slot_angles[i]
        angle = math.radians(angle_deg)
        x = int(math.cos(angle) * radius)
        y = int(math.sin(angle) * radius)
        color = colors[i]
        prefix = str(getattr(inst, "route_prefix", "") or "").strip("/")
        name = str(getattr(inst, "display_name", "Spoke page"))
        parts = [p for p in name.split() if p]
        if len(parts) >= 2:
            label = f"{parts[0]}<br>{parts[1]}"
        elif parts:
            label = parts[0]
        else:
            label = "Spoke<br>page"
        href = f"/{prefix}/" if prefix else "#"
        if not prefix:
            spoke_tag = f'<a class="node spoke" style="pointer-events:none;opacity:.92;--x:{x}px;--y:{y}px;--c:{color}" href="#">'
            spoke_close = "</a>"
        else:
            spoke_tag = f'<a class="node spoke" style="--x:{x}px;--y:{y}px;--c:{color}" href="{href}">'
            spoke_close = "</a>"
        spokes.append(
            f"""
      <div class="connector" style="--a:{angle_deg}deg;--r:{radius}px;--c:{color}"></div>
      {spoke_tag}
        <span class="spoke-label">{label}</span>
      {spoke_close}
"""
        )
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Hub MVA</title>
  <style>
""" + _base_styles() + """
  </style>
</head>
<body>
  <div class="container">
    <div class="title-wrap"><h1 class="title">Hub MVA</h1></div>
    <div class="hub-wrap">
      <div class="hub-diagram">
""" + "".join(spokes) + """
        <div class="hub-shell"></div>
        <div class="hub-core">
          <div class="hub-label-top">Contact Us</div>
          <div class="hub-center">
            <small>Customer</small>
            <small>Service</small>
          </div>
          <div class="hub-label-bottom">FAQ</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""
