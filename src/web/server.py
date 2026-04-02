from __future__ import annotations

import json
import os
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
import traceback
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from datetime import datetime

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


def _decode_text_payload(body: bytes, content_type: str) -> str | None:
    charset = ""
    try:
        match = re.search(r"charset=([^\s;]+)", content_type or "", flags=re.IGNORECASE)
        if match:
            charset = (match.group(1) or "").strip().strip("\"'")
    except Exception:
        charset = ""

    encodings = []
    if charset:
        encodings.append(charset)
    encodings.extend(["utf-8", "cp1252", "latin-1"])

    for enc in encodings:
        try:
            return body.decode(enc)
        except Exception:
            continue
    return None


def _normalize_ptbr_text(text: str) -> str:
    if not text:
        return text

    out = text
    markers = ("Ã", "Â", "â", "ðŸ", "�")
    if any(m in out for m in markers):
        try:
            repaired = out.encode("latin-1").decode("utf-8")
            if repaired:
                out = repaired
        except Exception:
            pass

    replacements = {
        "Ã¡": "á",
        "Ã¢": "â",
        "Ã£": "ã",
        "Ã ": "à",
        "Ã©": "é",
        "Ãª": "ê",
        "Ã­": "í",
        "Ã³": "ó",
        "Ã´": "ô",
        "Ãµ": "õ",
        "Ãº": "ú",
        "Ã§": "ç",
        "Ã": "Á",
        "Ã‰": "É",
        "Ã": "Í",
        "Ã“": "Ó",
        "Ãš": "Ú",
        "Ã‡": "Ç",
        "â€“": "–",
        "â€”": "—",
        "â€œ": "“",
        "â€": "”",
        "â€˜": "‘",
        "â€™": "’",
        "Â ": "",
    }
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out


def _inject_back_to_hub_button(html: str) -> str:
    if 'id="hub-back-button"' in html:
        return html

    snippet = """
<style id="hub-back-button-style">
#hub-back-button{
  position:fixed;
  top:16px;
  left:16px;
  z-index:2147483647;
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding:10px 14px;
  border-radius:999px;
  border:2px solid #176fe5;
  background:#ffffff;
  color:#176fe5;
  font-family:'Lexend',sans-serif;
  font-size:14px;
  font-weight:700;
  text-decoration:none;
  box-shadow:0 6px 18px rgba(23,111,229,.18);
}
#hub-back-button:hover{
  background:#176fe5;
  color:#ffffff;
}
</style>
<a id="hub-back-button" href="/" aria-label="Voltar ao Hub">← Voltar ao Hub</a>
"""
    if "</body>" in html:
        return html.replace("</body>", f"{snippet}\n</body>")
    return html + snippet


class HubHttpServer:
    def __init__(
        self,
        host: str,
        port: int,
        runtime: InstanceRuntimeManager,
        settings: AppSettingsStore,
        updater=None,
    ):
        self.host = host
        self.port = port
        self.runtime = runtime
        self.settings = settings
        self.updater = updater
        self.httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._procs: dict[str, subprocess.Popen] = {}
        self._proc_lock = threading.Lock()
        self._inst_updater_thread: threading.Thread | None = None
        self._inst_updater_stop = threading.Event()
        self._inst_updater_interval_minutes = 5
        self._inst_updater_git_missing_logged = False
        self._instance_update_restarts = 0
        logs_dir = Path(self.settings.base_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir = logs_dir
        self._debug_log_path = logs_dir / "instance_debug.log"

    def _diag(self, message: str):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line)
        try:
            with self._debug_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    @staticmethod
    def _clear_console() -> None:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass

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

    def _instance_log_paths(self, key: str) -> tuple[Path, Path]:
        safe_key = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (key or "instance"))
        out_path = self._logs_dir / f"{safe_key}_stdout.log"
        err_path = self._logs_dir / f"{safe_key}_stderr.log"
        return out_path, err_path

    def _ensure_backend_runtime(self, app_dir: str) -> bool:
        app_path = Path(app_dir)
        self._diag(f"[Runtime] Ensure runtime for {app_path}")
        if not app_path.exists():
            self._diag(f"[Runtime] App dir nao existe: {app_path}")
            return False

        venv_python = app_path / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            cmd = self._system_python_cmd() + ["-m", "venv", ".venv"]
            proc = subprocess.run(cmd, cwd=str(app_path), text=True, capture_output=True, check=False)
            if proc.returncode != 0:
                out = (proc.stderr or proc.stdout or "").strip()
                self._diag(f"[Runtime] Falha ao criar venv em {app_path}: {out}")
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
                self._diag(f"[Runtime] Falha ao atualizar pip em {app_path}: {out}")
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
                self._diag(f"[Runtime] Falha ao instalar requisitos em {app_path}: {out}")
                return False
            try:
                marker.write_text("ok", encoding="utf-8")
            except Exception:
                pass
            self._diag(f"[Runtime] Dependencias preparadas para {app_path}")

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
                out_path, err_path = self._instance_log_paths(key)
                self._diag(f"[Runtime] Iniciando {key}: cwd={app_dir} cmd={' '.join(cmd)}")
                self._diag(f"[Runtime] Logs {key}: stdout={out_path} stderr={err_path}")
                out_handle = open(out_path, "ab")
                err_handle = open(err_path, "ab")
                self._procs[key] = subprocess.Popen(
                    cmd,
                    cwd=app_dir,
                    stdout=out_handle,
                    stderr=err_handle,
                )
                out_handle.close()
                err_handle.close()
                self._diag(f"[Runtime] Processo {key} iniciado pid={self._procs[key].pid}")
                time.sleep(0.8)
                if self._procs[key].poll() is not None:
                    self._diag(f"[Runtime] Processo {key} encerrou logo apos iniciar (exit={self._procs[key].poll()})")
                return True
            except Exception as exc:
                self._diag(f"[Runtime] Erro iniciando {key}: {exc}")
                self._diag(traceback.format_exc())
                return False

    @staticmethod
    def _run_git(repo_dir: Path, *args: str) -> tuple[int, str]:
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            proc = subprocess.run(
                ["git", *args],
                cwd=str(repo_dir),
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode, out
        except Exception as exc:
            return 1, str(exc)

    def _restart_managed_instance(self, instance_id: str, app_dir: str, start_args: list[str]) -> bool:
        with self._proc_lock:
            proc = self._procs.get(instance_id)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=8)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                finally:
                    self._procs.pop(instance_id, None)
        return self._start_app_if_needed(instance_id, app_dir, start_args)

    def _update_instance_repo_once(self, inst: InstanceConfig) -> None:
        app_dir = Path(str(inst.app_dir or "")).resolve()
        if not app_dir.exists():
            return
        if not (app_dir / ".git").exists():
            return
        branch = str(inst.repo_branch or "main").strip() or "main"
        remote = "origin"

        code, out = self._run_git(app_dir, "fetch", remote, branch)
        if code != 0:
            if out:
                self._diag(f"[Instance Updater] {inst.display_name}: falha no fetch: {out}")
            return

        code_l, local_head = self._run_git(app_dir, "rev-parse", "HEAD")
        code_r, remote_head = self._run_git(app_dir, "rev-parse", f"{remote}/{branch}")
        if code_l != 0 or code_r != 0:
            return
        local_head = (local_head or "").strip()
        remote_head = (remote_head or "").strip()
        if not local_head or not remote_head or local_head == remote_head:
            return

        self._diag(
            f"[Instance Updater] {inst.display_name}: nova versao detectada "
            f"({local_head[:7]} -> {remote_head[:7]})"
        )
        code, out = self._run_git(app_dir, "pull", "--ff-only", remote, branch)
        if code != 0:
            if out:
                self._diag(f"[Instance Updater] {inst.display_name}: falha no pull: {out}")
            return

        code_n, new_head = self._run_git(app_dir, "rev-parse", "HEAD")
        new_head = (new_head or "").strip() if code_n == 0 else ""
        if not new_head or new_head == local_head:
            return

        self._diag(f"[Instance Updater] {inst.display_name}: atualizacao aplicada para {new_head[:7]}")
        restarted = self._restart_managed_instance(inst.instance_id, str(app_dir), list(inst.start_args or ["main.py"]))
        if restarted:
            self._instance_update_restarts += 1
            self._clear_console()
            print(
                "[Hub] Atualizacoes de instancias nesta sessao: "
                f"{self._instance_update_restarts}"
            )
            self._diag(f"[Instance Updater] {inst.display_name}: reiniciado com a nova versao")
        else:
            self._diag(
                f"[Instance Updater] {inst.display_name}: atualizado, mas nao foi possivel reiniciar automaticamente"
            )

    def _instance_updater_loop(self) -> None:
        self._diag(f"[Instance Updater] Ativo: intervalo={self._inst_updater_interval_minutes}min")
        # Primeira checagem imediata, igual comportamento esperado de startup.
        self._run_instance_update_cycle()
        while not self._inst_updater_stop.is_set():
            for _ in range(max(1, self._inst_updater_interval_minutes) * 60):
                if self._inst_updater_stop.is_set():
                    return
                time.sleep(1)
            if self._inst_updater_stop.is_set():
                return
            self._run_instance_update_cycle()

    def _run_instance_update_cycle(self) -> None:
        if shutil.which("git") is None:
            if not self._inst_updater_git_missing_logged:
                self._diag("[Instance Updater] Git nao encontrado. Atualizacao das instancias desativada")
                self._inst_updater_git_missing_logged = True
            return
        try:
            cfg = self.settings.load()
        except Exception:
            return
        for inst in cfg.instances:
            if not inst.enabled:
                continue
            self._update_instance_repo_once(inst)

    def start_instance_updater(self, enabled: bool, interval_minutes: int) -> None:
        self._inst_updater_stop.clear()
        self._inst_updater_interval_minutes = max(1, int(interval_minutes or 5))
        if not enabled:
            return
        if self._inst_updater_thread and self._inst_updater_thread.is_alive():
            return
        self._inst_updater_thread = threading.Thread(
            target=self._instance_updater_loop,
            daemon=True,
            name="instance-updater",
        )
        self._inst_updater_thread.start()

    def _clone_if_needed(self, inst: InstanceConfig) -> bool:
        app_path = Path(str(inst.app_dir or ""))
        if not inst.auto_clone_missing:
            return False
        if not inst.repo_url:
            return False
        if shutil.which("git") is None:
            return False
        if app_path.exists():
            # Pasta já existe: se for um repo válido ou tiver main.py, segue sem clonar.
            if (app_path / ".git").exists() or (app_path / "main.py").exists():
                return True
            # Tentativa de recuperação: pasta inválida/incompleta.
            try:
                backup = app_path.with_name(f"{app_path.name}_broken_{int(time.time())}")
                app_path.rename(backup)
                self._diag(
                    f"[Clone] {inst.display_name}: pasta existente sem main.py/.git movida para {backup}"
                )
            except Exception as exc:
                self._diag(
                    f"[Clone] {inst.display_name}: pasta {app_path} inválida e não foi possível mover: {exc}"
                )
                return False
        try:
            app_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--branch", inst.repo_branch or "main", inst.repo_url, str(app_path)]
            proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
            if proc.returncode != 0:
                out = (proc.stderr or proc.stdout or "").strip()
                self._diag(f"[Clone] Falha em {inst.display_name}: {out}")
                return False
            self._diag(f"[Clone] Repositorio clonado para {app_path}")
            return True
        except Exception as exc:
            self._diag(f"[Clone] Erro ao clonar {inst.display_name}: {exc}")
            self._diag(traceback.format_exc())
            return False

    def _ensure_backend_online(self, inst: InstanceConfig, quiet_if_online: bool = False) -> bool:
        if self._url_online(inst.backend_url):
            if not quiet_if_online:
                self._diag(f"[Warmup] Backend ja online: {inst.display_name}")
            return True
        self._diag(f"[Warmup] Ensure online {inst.display_name} -> {inst.backend_url}")
        if not inst.app_dir:
            return False
        if not self._clone_if_needed(inst):
            # se a pasta ja existir mas clone nao era necessario, segue normalmente
            if not Path(inst.app_dir).exists():
                return False
        if not self._start_app_if_needed(inst.instance_id, inst.app_dir, inst.start_args):
            self._diag(f"[Warmup] Falha ao iniciar processo de {inst.display_name}")
            return False
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._url_online(inst.backend_url):
                self._diag(f"[Warmup] Backend ficou online: {inst.display_name}")
                return True
            time.sleep(0.6)
        self._diag(f"[Warmup] Timeout aguardando backend: {inst.display_name}")
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
        text = _decode_text_payload(body, content_type)
        if text is None:
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

        text = _normalize_ptbr_text(text)
        if "text/html" in ctype:
            text = _inject_back_to_hub_button(text)

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
            _html_response(handler, 502, f"<h1>Backend indisponível</h1><p>{exc}</p>")

    def warm_up_enabled_backends(self) -> None:
        cfg = self.settings.load()
        for inst in cfg.instances:
            if not inst.enabled:
                continue
            ok = self._ensure_backend_online(inst)
            self._diag(f"[Warmup] {inst.display_name}: {'OK' if ok else 'FALHA'}")

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

                if path == "/hub/api/update/check":
                    if self.command not in {"GET", "POST"}:
                        return _json_response(self, 405, {"ok": False, "error": "Metodo nao permitido"})
                    expected = str(os.environ.get("HUB_UPDATE_WEBHOOK_SECRET", "")).strip()
                    query = urllib.parse.parse_qs(urlparse(self.path).query or "")
                    provided = str(self.headers.get("X-Hub-Token", "")).strip() or str(query.get("token", [""])[0]).strip()
                    if expected and provided != expected:
                        return _json_response(self, 403, {"ok": False, "error": "Token invalido"})
                    updater_ref = self.server.hub_ref.updater
                    if updater_ref is None:
                        return _json_response(self, 503, {"ok": False, "error": "Updater indisponivel"})
                    queued = bool(updater_ref.trigger_check(reason="api"))
                    return _json_response(self, 202, {"ok": queued, "queued": queued})

                for prefix, inst in by_prefix.items():
                    base = f"/{prefix}"
                    if path == base:
                        return _redirect_response(self, f"{base}/")
                    if path.startswith(f"{base}/"):
                        ok = self.server.hub_ref._ensure_backend_online(inst, quiet_if_online=True)
                        if not ok:
                            return _html_response(
                                self,
                                503,
                                f"<h1>{inst.display_name} indisponível</h1>"
                                "<p>Não foi possível iniciar ou alcançar o backend configurado.</p>",
                            )
                        return self.server.hub_ref._proxy(self, inst)

                return _json_response(self, 404, {"ok": False, "error": "Não encontrado"})

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
        self._inst_updater_stop.set()
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
                display_name="Em breve",
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
        name = str(getattr(inst, "display_name", "Em breve"))
        parts = [p for p in name.split() if p]
        if len(parts) >= 2:
            label = f"{parts[0]}<br>{parts[1]}"
        elif parts:
            label = parts[0]
        else:
            label = "Em breve"
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
  <title>FinanceAnaHub</title>
  <style>
""" + _base_styles() + """
  </style>
</head>
<body>
  <div class="container">
    <div class="title-wrap"><h1 class="title">FinanceAnaHub</h1></div>
    <div class="hub-wrap">
      <div class="hub-diagram">
""" + "".join(spokes) + """
        <div class="hub-shell"></div>
        <div class="hub-core">
          <div class="hub-label-top">Suporte</div>
          <div class="hub-center">
            <small>Central</small>
            <small>Hub</small>
          </div>
          <div class="hub-label-bottom">Ajuda</div>
        </div>
      </div>
    </div>
  </div>
  <div class="actions-panel" style="margin-top: 40px; border-top: 2px dashed #ccc; padding-top: 20px; display: flex; flex-direction: column; gap: 20px;">
    
    <div>
      <h3 style="margin-bottom: 10px;">Ferramentas de Manutenção (Botana)</h3>
      <button id="btn-corrigir" class="btn" onclick="iniciarCorrecao()" style="padding: 12px 24px; font-size: 16px; cursor: pointer; border-radius: 8px; border: none; background-color: #176fe5; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Corrigir Boletos Retrospectivos</button>
    </div>

    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; border: 1px solid #ddd;">
      <h3 style="margin-top: 0; margin-bottom: 15px;">Verificar NFs Faltantes</h3>
      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <select id="filtro-empresa" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc;">
            <option value="todos">Ambas as Empresas</option>
            <option value="MVA">Apenas MVA</option>
            <option value="EH">Apenas Horizonte (EH)</option>
        </select>
        <select id="filtro-tipo" onchange="mudarFiltro()" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc;">
            <option value="nfs">Por Range de NF</option>
            <option value="mes">Por Mês</option>
            <option value="todos">Toda a Planilha</option>
        </select>
        <div id="div-mes" style="display: none;">
            <input type="month" id="input-mes" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc;">
        </div>
        <div id="div-nfs" style="display: flex; align-items: center; gap: 5px;">
            <input type="number" id="input-nf-inicio" placeholder="De NF Ex: 49000" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 140px;">
            <span>até</span>
            <input type="number" id="input-nf-fim" placeholder="Até NF Ex: 50000" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 140px;">
        </div>
        <button id="btn-gerar-relatorio" onclick="gerarRelatorio()" style="padding: 10px 20px; font-size: 14px; cursor: pointer; border-radius: 8px; border: none; background-color: #28a745; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Verificar Faltantes</button>
        <button id="btn-baixar-csv" onclick="baixarCSV()" style="display: none; padding: 10px 20px; font-size: 14px; cursor: pointer; border-radius: 8px; border: none; background-color: #6c757d; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Baixar CSV</button>
      </div>
      <div id="resumo-container" style="margin-top: 15px; display: none; padding: 12px; border-radius: 6px; background: #e9ecef; font-size: 14px;"></div>
      <div id="tabela-container" style="margin-top: 15px; max-height: 400px; overflow-y: auto; display: none;">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
            <thead>
                <tr style="background-color: #f8d7da;">
                    <th style="padding: 8px; border: 1px solid #ddd;">#</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">NF Faltante</th>
                </tr>
            </thead>
            <tbody id="tabela-corpo"></tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
    let dadosRelatorioAtual = {};

    function mudarFiltro() {
        const tipo = document.getElementById("filtro-tipo").value;
        document.getElementById("div-mes").style.display = (tipo === "mes") ? "block" : "none";
        document.getElementById("div-nfs").style.display = (tipo === "nfs") ? "flex" : "none";
    }

    function gerarRelatorio() {
        const tipo = document.getElementById("filtro-tipo").value;
        const empresa = document.getElementById("filtro-empresa").value;
        let queryParams = new URLSearchParams();
        queryParams.append("filtro", tipo);
        queryParams.append("empresa", empresa);
        
        if (tipo === "mes") {
            queryParams.append("mes", document.getElementById("input-mes").value);
        } else if (tipo === "nfs") {
            queryParams.append("nf_inicio", document.getElementById("input-nf-inicio").value);
            queryParams.append("nf_fim", document.getElementById("input-nf-fim").value);
        }

        const btn = document.getElementById("btn-gerar-relatorio");
        btn.innerText = "Buscando...";
        btn.disabled = true;

        fetch("/botana/api/relatorio-nfs?" + queryParams.toString())
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.status === "success") {
                    dadosRelatorioAtual = data;
                    renderizarResultado();
                } else {
                    alert("Erro ao gerar relatório: " + (data.message || "Erro desconhecido"));
                }
            })
            .catch(function(err) { alert("Erro de rede: " + err); })
            .finally(function() {
                btn.innerText = "Verificar Faltantes";
                btn.disabled = false;
            });
    }

    function renderizarResultado() {
        var resumo = document.getElementById("resumo-container");
        var container = document.getElementById("tabela-container");
        var tbody = document.getElementById("tabela-corpo");
        var d = dadosRelatorioAtual;
        tbody.innerHTML = "";

        var totalFaltante = d.totalFaltante || 0;
        var totalEncontrado = d.totalEncontrado || 0;
        var totalEsperado = d.totalEsperado || 0;

        var corFundo = totalFaltante === 0 ? "#d4edda" : "#f8d7da";
        var mensagem = totalFaltante === 0
            ? "<b>Nenhuma NF faltante!</b> Todas as " + totalEncontrado + " NFs do intervalo " + d.rangeInicio + " a " + d.rangeFim + " estão presentes."
            : "<b>" + totalFaltante + " NF(s) faltante(s)</b> no intervalo " + d.rangeInicio + " a " + d.rangeFim + ". Encontradas: " + totalEncontrado + " de " + totalEsperado + " esperadas.";

        resumo.style.background = corFundo;
        resumo.innerHTML = mensagem;
        resumo.style.display = "block";

        if (totalFaltante > 0) {
            var faltantes = d.faltantes || [];
            for (var idx = 0; idx < faltantes.length; idx++) {
                var tr = document.createElement("tr");
                tr.innerHTML = '<td style="padding: 8px; border: 1px solid #ddd;">' + (idx + 1) + '</td><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; color: #c0392b;">' + faltantes[idx].NF + '</td>';
                tbody.appendChild(tr);
            }
            container.style.display = "block";
            document.getElementById("btn-baixar-csv").style.display = "inline-block";
        } else {
            container.style.display = "none";
            document.getElementById("btn-baixar-csv").style.display = "none";
        }
    }

    function baixarCSV() {
        var d = dadosRelatorioAtual;
        var faltantes = d.faltantes || [];
        if (faltantes.length === 0) return;
        
        var linhasCsv = ["NF Faltante"];
        for (var i = 0; i < faltantes.length; i++) {
            linhasCsv.push(String(faltantes[i].NF));
        }
        
        var blob = new Blob(["\\uFEFF" + linhasCsv.join("\\n")], { type: "text/csv;charset=utf-8;" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "nfs_faltantes_" + d.rangeInicio + "_a_" + d.rangeFim + ".csv";
        a.click();
        URL.revokeObjectURL(url);
    }

    function iniciarCorrecao() {
      const BOTAO_MENSAGEM = "Corrigir Boletos Retrospectivos";
      const BOTAO_MENSAGEM_CARREGANDO = "Processando...";
      const URL_CORRECAO = "/botana/api/clean-sheets";
      
      let botaoCorrigir = document.getElementById("btn-corrigir");
      botaoCorrigir.innerText = BOTAO_MENSAGEM_CARREGANDO;
      botaoCorrigir.disabled = true;
      botaoCorrigir.style.background = "#9cdaf8";
      
      fetch(URL_CORRECAO, { method: "POST" })
        .then((respostaServidor) => {
          return respostaServidor.json().then((dadosResposta) => {
            return [respostaServidor.ok, dadosResposta];
          });
        })
        .then(([sucessoRequisicao, dadosResposta]) => {
          if (sucessoRequisicao && dadosResposta.ok) {
            window.alert(dadosResposta.friendly || "Sistema de correção iniciado com sucesso em segundo plano!");
          } else {
            window.alert("Erro ao iniciar a correção: " + (dadosResposta.friendly || dadosResposta.message || "Erro desconhecido"));
          }
        })
        .catch((erroRequisicao) => {
          window.alert("Erro de comunicação com o servidor: " + erroRequisicao);
        })
        .finally(() => {
          botaoCorrigir.innerText = BOTAO_MENSAGEM;
          botaoCorrigir.disabled = false;
          botaoCorrigir.style.background = "#176fe5";
        });
    }
  </script>
</body>
</html>"""
