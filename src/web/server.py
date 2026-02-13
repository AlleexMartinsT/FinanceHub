from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
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
    def _python_cmd(app_dir: str) -> str:
        app_path = Path(app_dir)
        venv_python = app_path / ".venv" / "Scripts" / "python.exe"
        return str(venv_python) if venv_python.exists() else sys.executable

    def _start_app_if_needed(self, key: str, app_dir: str, args: list[str]) -> bool:
        with self._proc_lock:
            proc = self._procs.get(key)
            if proc is not None and proc.poll() is None:
                return True
            try:
                cmd = [self._python_cmd(app_dir)] + list(args or ["main.py"])
                self._procs[key] = subprocess.Popen(cmd, cwd=app_dir)
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
        # inbound_path ex: /empresa1/financeiro/api/status -> /api/status
        path = inbound_path[len(prefix) :]
        if not path.startswith("/"):
            path = "/" + path
        parsed = urlparse(base_url)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    @staticmethod
    def _rewrite_text_for_prefix(body: bytes, content_type: str, prefix: str) -> bytes:
        ctype = (content_type or "").lower()
        if "text/html" not in ctype and "javascript" not in ctype:
            return body
        try:
            text = body.decode("utf-8", errors="ignore")
        except Exception:
            return body

        text = text.replace('"/api/', f'"/{prefix}/api/')
        text = text.replace("'/api/", f"'/{prefix}/api/")
        text = text.replace('fetch("/api/', f'fetch("/{prefix}/api/')
        text = text.replace("fetch('/api/", f"fetch('/{prefix}/api/")

        text = text.replace('href="/logout"', f'href="/{prefix}/logout"')
        text = text.replace('href="/login"', f'href="/{prefix}/login"')
        text = text.replace('action="/login"', f'action="/{prefix}/login"')
        text = text.replace('action="/logout"', f'action="/{prefix}/logout"')

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
                        parsed = urlparse(v)
                        loc = parsed.path or "/"
                        if not loc.startswith(f"/{prefix}/"):
                            loc = f"/{prefix}{loc}"
                        handler.send_header("Location", loc)
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
    body{font-family:Arial,sans-serif;background:#f8f2eb;margin:0;padding:16px;color:#3f2a1d}
    .container{max-width:1100px;margin:0 auto}
    h1{margin:0 0 12px}
    .subtitle{margin:0 0 18px;color:#6e533f}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
    .card{background:#fff;border:1px solid #e6cdb6;border-radius:10px;padding:16px}
    .pill{display:inline-block;border-radius:999px;padding:3px 8px;background:#f3e4d5;margin-bottom:8px}
    .btn{border:0;border-radius:8px;padding:8px 10px;cursor:pointer;background:#c56a1a;color:#fff;text-decoration:none;display:inline-block}
    """


def _render_home_html(instances: list[InstanceConfig]) -> str:
    cards = []
    for inst in instances:
        prefix = inst.route_prefix.strip("/")
        cards.append(
            f"""
      <div class="card">
        <span class="pill">{inst.instance_type}</span>
        <h2>{inst.display_name}</h2>
        <p>{inst.notes or "Instancia configurada no HUB"}</p>
        <a class="btn" href="/{prefix}/">Abrir</a>
      </div>
"""
        )
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>FinanceAnaHub</title>
  <style>
""" + _base_styles() + """
  </style>
</head>
<body>
  <div class="container">
    <h1>FinanceAnaHub</h1>
    <p class="subtitle">Acesso centralizado por instancia</p>
    <div class="grid">
""" + "".join(cards) + """
    </div>
  </div>
</body>
</html>"""
