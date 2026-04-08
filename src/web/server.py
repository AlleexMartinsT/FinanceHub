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
import textwrap
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
        console_event_callback=None,
    ):
        self.host = host
        self.port = port
        self.runtime = runtime
        self.settings = settings
        self.updater = updater
        self._console_event_callback = console_event_callback
        self.httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._procs: dict[str, subprocess.Popen] = {}
        self._proc_lock = threading.Lock()
        self._inst_updater_thread: threading.Thread | None = None
        self._inst_updater_stop = threading.Event()
        self._inst_updater_interval_minutes = 5
        self._inst_updater_next_at = 0.0
        self._inst_updater_git_missing_logged = False
        self._instance_update_restarts = 0
        logs_dir = Path(self.settings.base_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir = logs_dir
        self._debug_log_path = logs_dir / "instance_debug.log"

    def _diag(self, message: str):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}"
        try:
            with self._debug_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        callback = self._console_event_callback
        if callable(callback):
            try:
                callback(line)
                return
            except Exception:
                pass
        console_block = self._runtime_console_hud(message=message, stamp=stamp)
        print(console_block if console_block else line)

    @staticmethod
    def _ascii_box(title: str, rows: list[str], width: int = 72) -> str:
        inner = max(24, int(width) - 4)
        top = "+" + "-" * (inner + 2) + "+"
        out = [top, f"| {str(title or '').strip()[:inner].ljust(inner)} |", top]
        for raw in rows or []:
            chunks = textwrap.wrap(str(raw or "").strip(), width=inner) or [""]
            for chunk in chunks:
                out.append(f"| {chunk.ljust(inner)} |")
        out.append(top)
        return "\n".join(out)

    def _runtime_console_hud(self, message: str, stamp: str) -> str | None:
        msg = str(message or "").strip()
        if not msg:
            return None

        if msg.startswith("[Hub] Atualizacoes de instancias nesta sessao:"):
            count = msg.rsplit(":", 1)[-1].strip() or "-"
            return self._ascii_box(
                "HUB INSTANCE UPDATE SESSION",
                [
                    f"Time    : {stamp}",
                    f"Updates : {count}",
                ],
            )

        match = re.match(r"^\[Instance Updater\]\s+(.+?):\s+reiniciado com a nova versao$", msg)
        if match:
            inst_name = match.group(1).strip() or "-"
            return self._ascii_box(
                "INSTANCE RESTARTED",
                [
                    f"Time     : {stamp}",
                    f"Instance : {inst_name}",
                    "Status   : restarted with the new version",
                    f"Session  : {self._instance_update_restarts} update(s) in this CMD",
                ],
            )

        match = re.match(r"^\[Warmup\]\s+Backend ficou online:\s+(.+)$", msg)
        if match:
            inst_name = match.group(1).strip() or "-"
            return self._ascii_box(
                "BACKEND ONLINE",
                [
                    f"Time     : {stamp}",
                    f"Instance : {inst_name}",
                    "Status   : backend is responding",
                ],
            )

        return None

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
            if not callable(self._console_event_callback):
                self._clear_console()
            self._diag(
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
        self._inst_updater_next_at = time.time()
        self._run_instance_update_cycle()
        self._inst_updater_next_at = time.time() + (max(1, self._inst_updater_interval_minutes) * 60)
        while not self._inst_updater_stop.is_set():
            for _ in range(max(1, self._inst_updater_interval_minutes) * 60):
                if self._inst_updater_stop.is_set():
                    self._inst_updater_next_at = 0.0
                    return
                time.sleep(1)
            if self._inst_updater_stop.is_set():
                self._inst_updater_next_at = 0.0
                return
            self._run_instance_update_cycle()
            self._inst_updater_next_at = time.time() + (max(1, self._inst_updater_interval_minutes) * 60)

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
            self._inst_updater_next_at = 0.0
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
        self._inst_updater_next_at = 0.0
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

    def get_console_state(self) -> dict:
        next_at = float(self._inst_updater_next_at or 0.0)
        remaining = max(0, int(next_at - time.time())) if next_at > 0 else 0
        return {
            "host": self.host,
            "port": int(self.port),
            "instance_update_restarts": int(self._instance_update_restarts),
            "instance_updater_interval_minutes": int(max(1, self._inst_updater_interval_minutes)),
            "next_instance_check_at": next_at,
            "next_instance_check_in_seconds": remaining,
            "instance_updater_running": bool(
                self._inst_updater_thread and self._inst_updater_thread.is_alive()
            ),
        }


def _base_styles() -> str:
    return """
    @import url('https://fonts.googleapis.com/css2?family=Lexend:wght@400;600;700;900&display=swap');
    :root{
      --bg:#f7f4ee;
      --bg-soft:#fffaf3;
      --card:#fffdf9;
      --card-alt:#f6fbff;
      --ink:#16202b;
      --muted:#5e6773;
      --line:#dfd5c8;
      --line-soft:#ece4d8;
      --hub:#176fe5;
      --hub-center:#9cdaf8;
      --accent:#ef8b51;
      --accent-soft:#fff1e3;
      --ok:#2f9e6f;
      --warn:#c67b1f;
      --shadow:0 22px 60px rgba(30,25,18,.10);
    }
    body{
      font-family:'Lexend',sans-serif;
      background:
        radial-gradient(circle at top left, rgba(23,111,229,.10), transparent 32%),
        radial-gradient(circle at top right, rgba(239,139,81,.10), transparent 26%),
        linear-gradient(180deg, #fbf7f1 0%, var(--bg) 100%);
      margin:0;
      padding:20px;
      color:var(--ink);
    }
    *{font-family:'Lexend',sans-serif}
    .container{max-width:1340px;margin:0 auto}
    .hero-panel{
      display:grid;
      grid-template-columns:minmax(0,1.42fr) minmax(340px,1fr);
      gap:22px;
      background:linear-gradient(135deg, rgba(255,255,255,.92), rgba(248,250,255,.96));
      border:1px solid rgba(23,111,229,.12);
      border-radius:28px;
      padding:28px;
      box-shadow:var(--shadow);
    }
    .hero-copy{text-align:left}
    .eyebrow{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 12px;
      border-radius:999px;
      background:rgba(23,111,229,.10);
      color:var(--hub);
      font-size:13px;
      font-weight:700;
      letter-spacing:.03em;
      text-transform:uppercase;
    }
    .title-wrap{display:inline-block;position:relative;margin-top:14px}
    .title-wrap::after{content:"";position:absolute;left:-10px;right:-10px;height:16px;bottom:7px;background:#d8f1ff;z-index:0;border-radius:999px}
    .title{position:relative;z-index:1;font-size:62px;font-weight:900;line-height:.95;margin:0}
    .subtitle{
      margin:18px 0 0;
      max-width:780px;
      color:var(--muted);
      font-size:18px;
      line-height:1.6;
    }
    .metric-grid{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:12px;
      margin-top:22px;
    }
    .metric-card{
      background:var(--card);
      border:1px solid var(--line-soft);
      border-radius:20px;
      padding:18px 16px;
      min-height:110px;
      box-shadow:0 10px 28px rgba(22,32,43,.05);
    }
    .metric-card strong{
      display:block;
      font-size:34px;
      line-height:1;
      color:var(--hub);
    }
    .metric-card span{
      display:block;
      margin-top:10px;
      font-size:13px;
      color:var(--muted);
      line-height:1.45;
    }
    .chip-row{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      margin-top:18px;
    }
    .chip{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:10px 14px;
      border-radius:999px;
      background:#fff;
      border:1px solid var(--line-soft);
      color:#2d3b4a;
      font-size:14px;
      font-weight:600;
    }
    .chip::before{
      content:"";
      width:8px;
      height:8px;
      border-radius:999px;
      background:var(--ok);
      flex:0 0 auto;
    }
    .hero-note{
      background:linear-gradient(180deg, var(--card), #fff7ee);
      border:1px solid rgba(239,139,81,.20);
      border-radius:24px;
      padding:24px;
      text-align:left;
    }
    .hero-note h2{margin:0;font-size:24px;line-height:1.1}
    .hero-note p{margin:12px 0 0;color:var(--muted);font-size:15px;line-height:1.6}
    .hero-note-grid{
      display:grid;
      gap:12px;
      margin-top:18px;
    }
    .hero-note-item{
      background:rgba(255,255,255,.74);
      border:1px solid rgba(239,139,81,.16);
      border-radius:18px;
      padding:14px 16px;
    }
    .hero-note-item strong{display:block;font-size:15px}
    .hero-note-item span{display:block;margin-top:6px;font-size:13px;line-height:1.5;color:var(--muted)}
    .hub-panel{
      margin-top:24px;
      background:rgba(255,255,255,.80);
      border:1px solid rgba(22,32,43,.08);
      border-radius:28px;
      padding:24px;
      box-shadow:var(--shadow);
    }
    .panel-head{
      display:flex;
      justify-content:space-between;
      gap:18px;
      align-items:flex-start;
      margin-bottom:18px;
    }
    .panel-title-wrap{text-align:left}
    .panel-kicker{
      font-size:12px;
      font-weight:700;
      letter-spacing:.08em;
      text-transform:uppercase;
      color:var(--hub);
    }
    .panel-title{
      margin:8px 0 0;
      font-size:28px;
      line-height:1.1;
    }
    .panel-copy{
      margin:8px 0 0;
      color:var(--muted);
      font-size:15px;
      line-height:1.6;
      max-width:760px;
    }
    .panel-pill{
      display:inline-flex;
      align-items:center;
      padding:10px 14px;
      border-radius:999px;
      background:var(--accent-soft);
      color:#8b4d1f;
      font-size:13px;
      font-weight:700;
      white-space:nowrap;
    }
    .hub-layout{
      display:grid;
      grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);
      gap:26px;
      align-items:center;
    }
    .hub-stage{
      background:linear-gradient(180deg, #f7fbff, #fff8f1);
      border:1px solid var(--line-soft);
      border-radius:24px;
      padding:18px 18px 20px;
    }
    .hub-wrap{display:flex;justify-content:center;align-items:center}
    .hub-diagram{position:relative;width:680px;height:680px;max-width:100%;max-height:100%}
    .node{
      position:absolute;
      left:50%;
      top:50%;
      transform:translate(calc(-50% + var(--x)), calc(-50% + var(--y)));
      display:flex;
      align-items:center;
      justify-content:center;
      text-decoration:none;
      color:#232323;
      transition:transform .22s ease, filter .22s ease;
    }
    .node:hover{transform:translate(calc(-50% + var(--x)), calc(-50% + var(--y))) scale(1.04);filter:drop-shadow(0 14px 20px rgba(22,32,43,.10))}
    .spoke{
      width:128px;
      height:128px;
      border-radius:999px;
      background:#fff;
      border:6px solid var(--c);
      box-sizing:border-box;
      padding:12px;
      text-align:center;
      box-shadow:0 18px 24px rgba(22,32,43,.08);
    }
    .spoke-label{
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:center;
      gap:8px;
      min-height:100%;
      text-align:center;
    }
    .spoke-label strong{display:block;font-size:18px;font-weight:700;line-height:1.1}
    .spoke-meta{
      display:inline-flex;
      padding:5px 10px;
      border-radius:999px;
      background:rgba(22,32,43,.06);
      font-size:11px;
      font-weight:700;
      letter-spacing:.04em;
      text-transform:uppercase;
      color:#526070;
    }
    .connector{
      position:absolute;
      left:50%;
      top:50%;
      width:5px;
      height:116px;
      background:var(--c);
      border-radius:999px;
      transform:translate(-50%,-50%) rotate(var(--a)) translateY(-172px);
      transform-origin:center;
      opacity:.85;
    }
    .hub-shell{position:absolute;left:50%;top:50%;width:244px;height:244px;border-radius:999px;transform:translate(-50%,-50%);background:conic-gradient(#5f87d9 0 60deg,#45c3ac 60deg 120deg,#b6d45b 120deg 180deg,#f2ac73 180deg 240deg,#e2926a 240deg 300deg,#5f87d9 300deg 360deg);box-shadow:0 18px 28px rgba(22,32,43,.12)}
    .hub-core{position:absolute;left:50%;top:50%;width:226px;height:226px;border-radius:999px;transform:translate(-50%,-50%);background:var(--hub);display:flex;align-items:center;justify-content:center}
    .hub-center{width:112px;height:112px;border-radius:999px;background:var(--hub-center);display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:700;font-size:38px;line-height:1.02;color:#0f172a}
    .hub-center small{font-size:15px;font-weight:700}
    .hub-label-top{position:absolute;left:50%;top:62px;transform:translateX(-50%) rotate(-10deg);color:#fff;font-size:28px;font-weight:700;line-height:1}
    .hub-label-bottom{position:absolute;left:50%;bottom:52px;transform:translateX(-50%);color:#fff;font-size:30px;font-weight:700;line-height:1}
    .hub-caption{
      margin:14px 12px 0;
      text-align:center;
      color:var(--muted);
      font-size:14px;
      line-height:1.6;
    }
    .guide-card{
      background:linear-gradient(180deg, var(--card), #f7fcff);
      border:1px solid var(--line-soft);
      border-radius:24px;
      padding:22px;
      text-align:left;
    }
    .guide-card h3{margin:8px 0 0;font-size:24px;line-height:1.15}
    .guide-card p{margin:10px 0 0;color:var(--muted);font-size:14px;line-height:1.6}
    .guide-list{display:grid;gap:12px;margin-top:18px}
    .guide-item{
      background:#fff;
      border:1px solid var(--line-soft);
      border-radius:18px;
      padding:14px 16px;
    }
    .guide-item strong{display:block;font-size:14px}
    .guide-item span{display:block;margin-top:6px;color:var(--muted);font-size:13px;line-height:1.45}
    .actions-panel{
      margin-top:24px;
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:20px;
    }
    .tool-card{
      background:var(--card);
      border:1px solid var(--line);
      border-radius:26px;
      padding:24px;
      box-shadow:var(--shadow);
    }
    .tool-card.tool-card-primary{background:linear-gradient(180deg, #f5f9ff, #fffdfb)}
    .tool-card.tool-card-secondary{background:linear-gradient(180deg, #fffefb, #f9f7f2)}
    .tool-head{
      display:flex;
      justify-content:space-between;
      gap:14px;
      align-items:flex-start;
    }
    .tool-kicker{
      margin:0;
      color:var(--hub);
      font-size:12px;
      font-weight:700;
      letter-spacing:.08em;
      text-transform:uppercase;
    }
    .tool-head h3{margin:8px 0 0;font-size:26px;line-height:1.12}
    .tool-head p{margin:10px 0 0;color:var(--muted);font-size:14px;line-height:1.6}
    .tool-badge{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:9px 12px;
      border-radius:999px;
      background:rgba(23,111,229,.10);
      color:var(--hub);
      font-size:12px;
      font-weight:700;
      text-transform:uppercase;
      letter-spacing:.04em;
      white-space:nowrap;
    }
    .tool-helper{
      margin-top:14px;
      padding:14px 16px;
      border-radius:18px;
      background:var(--bg-soft);
      border:1px solid var(--line-soft);
      color:var(--muted);
      font-size:14px;
      line-height:1.6;
    }
    .actions-panel .tool-head{
      flex-direction:column;
      align-items:center;
      text-align:center;
    }
    .actions-panel .tool-head > div{
      max-width:660px;
      text-align:center;
    }
    .actions-panel .tool-helper{
      text-align:center;
    }
    .maintenance-controls{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:12px;
      align-items:end;
      margin-top:16px;
    }
    .maintenance-controls,.actions-panel #nf-faltantes-controls{
      justify-items:center;
    }
    .maintenance-controls > div,.actions-panel #nf-faltantes-controls > div{
      width:100%;
      max-width:320px;
      text-align:center;
    }
    .maintenance-controls label,.actions-panel #nf-faltantes-controls label{
      display:block;
      text-align:center;
    }
    #btn-corrigir,#btn-gerar-relatorio,#btn-baixar-csv{
      justify-self:center;
      max-width:240px;
    }
    #nf-faltantes-card{padding:24px}
    #nf-faltantes-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end;margin-top:16px}
    #nf-faltantes-controls > *{min-width:0}
    #nf-faltantes-controls select,#nf-faltantes-controls input,#nf-faltantes-controls button{width:100%;box-sizing:border-box}
    #nf-faltantes-actions{display:none;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;margin-top:14px;padding:14px 16px;border:1px solid #d9d0c5;border-radius:16px;background:#fff8ee}
    #nf-faltantes-actions button{width:auto;min-width:260px}
    .nf-action-meta{display:flex;flex-direction:column;gap:4px}
    .nf-action-toggle{display:flex;align-items:center;gap:10px;font-weight:700;color:#2f3a45}
    .nf-action-toggle input{width:18px;height:18px;flex:0 0 auto}
    .nf-action-hint{font-size:13px;color:#5d6b7b}
    #nf-faltantes-feedback{display:none;margin-top:12px;padding:14px 16px;border-radius:16px;border:1px solid #d8d0c4;background:#fffefa;color:#253243}
    #nf-faltantes-feedback.active{display:block}
    #nf-faltantes-feedback.error{display:block;background:#fff0f0;border-color:#efb8b8;color:#7a1f1f}
    #nf-faltantes-feedback.success{display:block;background:#edf9ef;border-color:#bcdcbc;color:#255133}
    .nf-progress-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
    .nf-progress-title{font-size:14px;font-weight:800;color:#243140}
    .nf-progress-count{font-size:12px;font-weight:700;color:#607084;white-space:nowrap}
    .nf-progress-track{margin-top:10px;height:12px;border-radius:999px;background:#e9edf2;overflow:hidden;position:relative}
    .nf-progress-fill{height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,#2f9e6f,#55c6a4);transition:width .35s ease}
    .nf-progress-fill.indeterminate{width:36%;background:linear-gradient(90deg,#4c8af0,#7bc2ff);animation:nf-progress-slide 1.15s ease-in-out infinite}
    .nf-progress-fill.error{background:linear-gradient(90deg,#d25d5d,#f08a8a)}
    .nf-progress-fill.success{background:linear-gradient(90deg,#2f9e6f,#74d39a)}
    .nf-progress-note{margin-top:8px;font-size:12px;line-height:1.45;color:#627080}
    #nf-faltantes-feedback.error .nf-progress-title,#nf-faltantes-feedback.error .nf-progress-count,#nf-faltantes-feedback.error .nf-progress-note{color:#7a1f1f}
    #nf-faltantes-feedback.success .nf-progress-title,#nf-faltantes-feedback.success .nf-progress-count,#nf-faltantes-feedback.success .nf-progress-note{color:#255133}
    .auth-pop-overlay{position:fixed;inset:0;background:rgba(15,23,42,.48);display:none;align-items:center;justify-content:center;padding:18px;z-index:9999}
    .auth-pop-overlay.show{display:flex}
    .auth-pop-card{width:min(100%,460px);background:#fffdf9;border:1px solid #ddd4c8;border-radius:24px;box-shadow:0 24px 80px rgba(15,23,42,.18);padding:24px;text-align:center}
    .auth-pop-kicker{margin:0;color:var(--hub);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
    .auth-pop-card h4{margin:10px 0 0;font-size:28px;line-height:1.08}
    .auth-pop-card p{margin:12px 0 0;color:var(--muted);font-size:14px;line-height:1.6}
    .auth-pop-actions{display:flex;gap:12px;justify-content:center;align-items:center;flex-wrap:wrap;margin-top:18px}
    .auth-pop-actions button{width:auto;min-width:180px}
    @keyframes nf-progress-slide{
      0%{transform:translateX(-120%)}
      100%{transform:translateX(320%)}
    }
    .nf-col-select{width:72px;text-align:center}
    .nf-select-cell{text-align:center}
    .nf-select-cell input{width:18px;height:18px}
    #div-mes{
      grid-column:1/-1;
      width:min(100%,260px);
      justify-self:center;
      text-align:center;
    }
    #div-mes input{text-align:center}
    #div-nfs{
      display:grid;
      grid-column:1/-1;
      grid-template-columns:minmax(0,1fr) 48px minmax(0,1fr);
      align-items:center;
      gap:8px;
      width:min(100%,560px);
      justify-self:center;
    }
    #div-nfs input{text-align:center}
    #div-nfs span{text-align:center;font-size:13px;font-weight:700;color:#475569}
    select,input{
      width:100%;
      box-sizing:border-box;
      padding:12px 14px;
      border-radius:14px;
      border:1px solid #d8d0c4;
      background:#fffefa;
      color:var(--ink);
      font-size:14px;
      outline:none;
      transition:border-color .2s ease, box-shadow .2s ease;
    }
    select:focus,input:focus{
      border-color:rgba(23,111,229,.55);
      box-shadow:0 0 0 4px rgba(23,111,229,.10);
    }
    button{
      width:100%;
      box-sizing:border-box;
      padding:12px 16px;
      border:0;
      border-radius:14px;
      cursor:pointer;
      font-size:14px;
      font-weight:700;
      transition:transform .18s ease, box-shadow .18s ease, opacity .18s ease;
    }
    button:hover{transform:translateY(-1px);box-shadow:0 10px 22px rgba(22,32,43,.10)}
    button:disabled{cursor:default;opacity:.72;transform:none;box-shadow:none}
    .btn-primary{background:var(--hub);color:#fff}
    .btn-secondary{background:#2f9e6f;color:#fff}
    .btn-neutral{background:#5a6471;color:#fff}
    #correcao-log-container{
      display:none;
      margin-top:16px;
      background:#151b27;
      color:#d5def4;
      border-radius:18px;
      padding:14px;
      max-height:320px;
      overflow-y:auto;
      font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size:12px;
      line-height:1.7;
      border:1px solid rgba(156,218,248,.18);
    }
    #resumo-container{
      margin-top:16px;
      display:none;
      padding:14px 16px;
      border-radius:18px;
      background:#eef3f7;
      font-size:14px;
      line-height:1.6;
      border:1px solid #d7dde4;
    }
    #tabela-container{
      margin-top:16px;
      max-height:400px;
      overflow-y:auto;
      display:none;
      border:1px solid var(--line-soft);
      border-radius:18px;
      background:#fff;
    }
    .data-table{width:100%;border-collapse:collapse;text-align:left}
    .data-table thead tr{background:#fff2e9}
    .data-table th,.data-table td{padding:10px 12px;border-bottom:1px solid var(--line-soft)}
    .data-table tbody tr:nth-child(even){background:#fffcf8}
    .data-table tbody tr:hover{background:#fff4ea}
    @media (max-width:760px){
      body{padding:14px}
      .hero-panel,.hub-layout,.actions-panel{grid-template-columns:1fr}
      .panel-head,.tool-head{flex-direction:column}
      .metric-grid,.maintenance-controls{grid-template-columns:1fr}
      .title{font-size:44px}
      .hub-diagram{width:540px;height:540px}
      .spoke{width:106px;height:106px;border-width:5px;padding:8px}
      .spoke-label strong{font-size:15px}
      .spoke-meta{font-size:10px;padding:4px 8px}
      .connector{height:90px;transform:translate(-50%,-50%) rotate(var(--a)) translateY(-136px)}
      .hub-shell{width:194px;height:194px}
      .hub-core{width:180px;height:180px}
      .hub-center{width:88px;height:88px;font-size:28px}
      .hub-center small{font-size:12px}
      .hub-label-top{top:48px;font-size:22px}
      .hub-label-bottom{bottom:38px;font-size:22px}
      #nf-faltantes-controls{grid-template-columns:1fr}
      #nf-faltantes-actions{grid-template-columns:1fr}
      #nf-faltantes-actions button{width:100%}
      #div-nfs{grid-template-columns:1fr}
      #btn-corrigir,#btn-gerar-relatorio,#btn-baixar-csv{max-width:none;width:100%}
      .auth-pop-actions{flex-direction:column}
      .auth-pop-actions button{width:100%}
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
    enabled_instances = [inst for inst in instances if bool(getattr(inst, "enabled", True))]
    routed_instances = [inst for inst in enabled_instances if str(getattr(inst, "route_prefix", "") or "").strip()]
    botana_instances = [inst for inst in routed_instances if str(getattr(inst, "instance_type", "") or "").strip().lower() == "botana"]
    finance_instances = [inst for inst in routed_instances if str(getattr(inst, "instance_type", "") or "").strip().lower() != "botana"]
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
        type_label = str(getattr(inst, "instance_type", "") or "modulo").strip().lower()
        if not prefix:
            meta_label = "Em breve"
        elif type_label == "botana":
            meta_label = "Botana"
        else:
            meta_label = "Financeiro"
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
        <span class="spoke-label"><strong>{label}</strong><span class="spoke-meta">{meta_label}</span></span>
      {spoke_close}
"""
        )
    metrics_active = str(len(routed_instances))
    metrics_botana = str(len(botana_instances))
    metrics_finance = str(len(finance_instances))
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
    <section class="hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">CMD do Servidor • HUD Central</span>
        <div class="title-wrap"><h1 class="title">FinanceAnaHub</h1></div>
        <p class="subtitle">
          O servidor agora concentra navegação, manutenção e validações financeiras em uma mesma HUD.
          A ideia aqui é reduzir tentativa e erro: você entra, entende o estado do ambiente e já cai no fluxo certo.
        </p>
        <div class="metric-grid">
          <div class="metric-card">
            <strong>""" + metrics_active + """</strong>
            <span>Módulos com rota pronta para abrir direto pelo hub.</span>
          </div>
          <div class="metric-card">
            <strong>""" + metrics_botana + """</strong>
            <span>Instância(s) Botana disponíveis para processamento e manutenção.</span>
          </div>
          <div class="metric-card">
            <strong>""" + metrics_finance + """</strong>
            <span>Painéis financeiros disponíveis para consulta e operação.</span>
          </div>
        </div>
        <div class="chip-row">
          <span class="chip">Correção guiada de boletos retrospectivos</span>
          <span class="chip">Verificação rápida de NFs faltantes</span>
          <span class="chip">Acesso centralizado aos módulos do ambiente</span>
        </div>
      </div>
      <aside class="hero-note">
        <h2>O que dá para resolver daqui</h2>
        <p>Esta HUD deixa o caminho mais explícito: primeiro você escolhe o módulo, depois aciona a ferramenta certa e acompanha o retorno sem depender só de texto solto.</p>
        <div class="hero-note-grid">
          <div class="hero-note-item">
            <strong>Entrar no módulo certo</strong>
            <span>O diagrama central mostra os atalhos ativos do ambiente para reduzir navegação manual.</span>
          </div>
          <div class="hero-note-item">
            <strong>Corrigir base antiga</strong>
            <span>A manutenção do Botana fica logo abaixo, com foco em correções retroativas e log contínuo.</span>
          </div>
          <div class="hero-note-item">
            <strong>Checar cobertura da planilha</strong>
            <span>O bloco de NFs faltantes resume o problema, destaca o intervalo e permite exportar o resultado.</span>
          </div>
        </div>
      </aside>
    </section>

    <section class="hub-panel">
      <div class="panel-head">
        <div class="panel-title-wrap">
          <div class="panel-kicker">Mapa operacional</div>
          <h2 class="panel-title">Escolha o módulo pelo fluxo, não pelo chute</h2>
          <p class="panel-copy">Cada círculo leva para um módulo ativo. O centro continua como ponto de orientação e os atalhos ao redor ajudam a separar rapidamente o que é Botana do que é frente financeira.</p>
        </div>
        <div class="panel-pill">Ambiente local organizado para operação diária</div>
      </div>
      <div class="hub-layout">
        <div class="hub-stage">
          <div class="hub-wrap">
            <div class="hub-diagram">
""" + "".join(spokes) + """
              <div class="hub-shell"></div>
              <div class="hub-core">
                <div class="hub-label-top">Servidor</div>
                <div class="hub-center">
                  <small>Central</small>
                  <small>Hub</small>
                </div>
                <div class="hub-label-bottom">CMD</div>
              </div>
            </div>
          </div>
          <p class="hub-caption">Os atalhos em volta do núcleo refletem os módulos prontos para uso. Os cards abaixo complementam essa navegação com ações operacionais guiadas.</p>
        </div>
        <aside class="guide-card">
          <div class="panel-kicker">Leitura rápida</div>
          <h3>Quando usar cada bloco</h3>
          <p>A HUD foi reorganizada para ficar mais clara: primeiro você entra no módulo, depois usa a manutenção ou o diagnóstico que resolve o problema com menos passos.</p>
          <div class="guide-list">
            <div class="guide-item">
              <strong>Módulos ao centro</strong>
              <span>Abra o destino certo sem depender de lembrar rota ou porta manualmente.</span>
            </div>
            <div class="guide-item">
              <strong>Manutenção do Botana</strong>
              <span>Use quando o problema é retroativo, estrutural ou precisa de correção assistida com log.</span>
            </div>
            <div class="guide-item">
              <strong>NFs faltantes</strong>
              <span>Use quando a dúvida é cobertura da planilha: faixa, mês, empresa e exportação no mesmo bloco.</span>
            </div>
          </div>
        </aside>
      </div>
    </section>

    <section class="actions-panel">
      <section class="tool-card tool-card-primary">
        <div class="tool-head">
          <div>
            <p class="tool-kicker">Manutenção Guiada</p>
            <h3>Corrigir boletos retrospectivos</h3>
            <p>Acione o assistente do Botana sem sair da HUD. O foco aqui é correção de base antiga com retorno contínuo para você acompanhar o que está acontecendo.</p>
          </div>
          <span class="tool-badge">Botana</span>
        </div>
        <div class="tool-helper">Escolha a empresa, filtre a aba se quiser reduzir o escopo e acompanhe o log abaixo. O card fica com linguagem mais operacional para não te deixar preso em termos soltos.</div>
        <div class="maintenance-controls">
          <div>
            <label for="correcao-empresa">Empresa</label>
            <select id="correcao-empresa">
            <option value="todos">Ambas as Empresas</option>
            <option value="MVA">Apenas MVA</option>
            <option value="EH">Apenas Horizonte (EH)</option>
          </select>
          </div>
          <div>
            <label for="correcao-aba">Aba específica</label>
            <input type="text" id="correcao-aba" placeholder="Filtrar por aba, ex: Janeiro">
          </div>
          <button id="btn-corrigir" class="btn-primary" onclick="iniciarCorrecao()">Iniciar Correção</button>
        </div>
        <div id="correcao-log-container"></div>
      </section>

      <section id="nf-faltantes-card" class="tool-card tool-card-secondary">
        <div class="tool-head">
          <div>
            <p class="tool-kicker">Diagnóstico de Planilha</p>
            <h3>Verificar NFs faltantes</h3>
            <p>Escolha o recorte de análise e o Hub resume o que falta, o que foi encontrado e deixa a exportação pronta quando houver divergência.</p>
          </div>
          <span class="tool-badge">Financeiro</span>
        </div>
        <div class="tool-helper">Use este bloco quando a pergunta for cobertura da planilha. O fluxo foi mantido responsivo e com navegação por Enter para acelerar a conferência no dia a dia.</div>
        <div id="nf-faltantes-controls">
        <div>
          <label for="filtro-empresa">Empresa</label>
          <select id="filtro-empresa">
            <option value="todos">Ambas as Empresas</option>
            <option value="MVA">Apenas MVA</option>
            <option value="EH">Apenas Horizonte (EH)</option>
          </select>
        </div>
        <div>
          <label for="filtro-tipo">Tipo de busca</label>
          <select id="filtro-tipo" onchange="mudarFiltro()">
            <option value="nfs">Por Range de NF</option>
            <option value="mes">Por Mês</option>
            <option value="todos">Toda a Planilha</option>
          </select>
        </div>
        <div id="div-mes" style="display: none;">
            <label for="input-mes">Mês</label>
            <input type="month" id="input-mes">
        </div>
        <div id="div-nfs">
            <input type="number" id="input-nf-inicio" placeholder="De NF Ex: 49000">
            <span>até</span>
            <input type="number" id="input-nf-fim" placeholder="Até NF Ex: 50000">
        </div>
        <button id="btn-gerar-relatorio" class="btn-secondary" onclick="gerarRelatorio()">Verificar Faltantes</button>
        <button id="btn-baixar-csv" class="btn-neutral" onclick="baixarCSV()" style="display: none;">Baixar CSV</button>
      </div>
      <div id="resumo-container"></div>
      <div id="nf-faltantes-actions">
        <div class="nf-action-meta">
          <label class="nf-action-toggle" for="nf-select-all">
            <input id="nf-select-all" type="checkbox" onchange="toggleSelecionarTodasFaltantes(this)">
            <span>Selecionar todas as NFs faltantes</span>
          </label>
          <div id="nf-selection-summary" class="nf-action-hint">Nenhuma NF faltante selecionada.</div>
        </div>
        <button id="btn-recuperar-faltantes" class="btn-primary" onclick="recuperarFaltantesSelecionadas()" disabled>Recuperar NFs</button>
      </div>
      <div id="nf-faltantes-feedback">
        <div class="nf-progress-head">
          <span id="nf-feedback-title" class="nf-progress-title">Recuperando no Botana</span>
          <span id="nf-feedback-count" class="nf-progress-count">0/0</span>
        </div>
        <div class="nf-progress-track">
          <div id="nf-feedback-bar" class="nf-progress-fill"></div>
        </div>
        <div id="nf-feedback-note" class="nf-progress-note"></div>
      </div>
      <div id="tabela-container">
        <table class="data-table">
            <thead>
                <tr>
                    <th class="nf-col-select">Selecionar</th>
                    <th>#</th>
                    <th>NF Faltante</th>
                </tr>
            </thead>
            <tbody id="tabela-corpo"></tbody>
        </table>
      </div>
      </section>
    </section>
    <div id="botana-auth-pop" class="auth-pop-overlay" aria-hidden="true">
      <div class="auth-pop-card" role="dialog" aria-modal="true" aria-labelledby="botana-auth-title">
        <p class="auth-pop-kicker">Botana</p>
        <h4 id="botana-auth-title">Login necessario</h4>
        <p id="botana-auth-msg">Voce precisa entrar no Botana antes de iniciar essa recuperacao.</p>
        <div class="auth-pop-actions">
          <button type="button" class="btn-primary" onclick="abrirLoginBotana()">Abrir login do Botana</button>
          <button type="button" class="btn-neutral" onclick="fecharLoginBotana()">Agora nao</button>
        </div>
      </div>
    </div>
  </div>
  <script>
    let dadosRelatorioAtual = {};
    let _nfRecoveryPollTimer = null;
    let _nfRecoveryPollAttempts = 0;
    let _nfRecoverySeenAction = false;

    function _normalizeUiText(value) {
        var text = String(value || "");
        if (!text) return "";
        [
            ["NÃ£o", "Não"],
            ["nÃ£o", "não"],
            ["AutenticaÃ§Ã£o", "Autenticação"],
            ["autenticaÃ§Ã£o", "autenticação"],
            ["RecuperaÃ§Ã£o", "Recuperação"],
            ["recuperaÃ§Ã£o", "recuperação"],
            ["solicitaÃ§Ã£o", "solicitação"],
            ["possÃ­vel", "possível"],
            ["concluÃ­da", "concluída"],
            ["navegaÃ§Ã£o", "navegação"],
            ["CorreÃ§Ã£o", "Correção"],
            ["correÃ§Ã£o", "correção"],
            ["MÃªs", "Mês"],
            ["mÃªs", "mês"],
            ["especÃ­fica", "específica"],
            ["contÃ­nuo", "contínuo"],
            ["vocÃª", "você"],
            ["estÃ¡", "está"],
            ["atÃ©", "até"],
            ["Ãª", "ê"],
            ["Ã¡", "á"],
            ["Ã£", "ã"],
            ["Ã§", "ç"],
            ["Ã³", "ó"],
            ["Ãº", "ú"],
            ["Ã­", "í"],
            ["Ã©", "é"]
        ].forEach(function(pair) {
            text = text.split(pair[0]).join(pair[1]);
        });
        return text;
    }

    function _isBotanaAuthError(statusCode, message) {
        var msg = _normalizeUiText(message).toLowerCase();
        return Number(statusCode) === 401
            || Number(statusCode) === 403
            || msg.indexOf("não autenticado") !== -1
            || msg.indexOf("nao autenticado") !== -1
            || msg.indexOf("sem permissão") !== -1
            || msg.indexOf("sem permissao") !== -1;
    }

    function abrirLoginBotana() {
        window.open("/botana/login", "botana-login", "width=720,height=840,resizable=yes,scrollbars=yes");
    }

    function fecharLoginBotana() {
        var el = document.getElementById("botana-auth-pop");
        if (!el) return;
        el.classList.remove("show");
        el.setAttribute("aria-hidden", "true");
    }

    function mostrarLoginBotana(message) {
        var el = document.getElementById("botana-auth-pop");
        var msgEl = document.getElementById("botana-auth-msg");
        if (!el || !msgEl) return;
        msgEl.textContent = _normalizeUiText(message || "Você precisa entrar no Botana antes de iniciar essa recuperação.");
        el.classList.add("show");
        el.setAttribute("aria-hidden", "false");
    }

    function _nfCheckboxes() {
        return Array.from(document.querySelectorAll(".nf-faltante-check"));
    }

    function _nfsFaltantesSelecionadas() {
        return _nfCheckboxes()
            .filter(function(el) { return !!el.checked; })
            .map(function(el) { return String(el.value || "").trim(); })
            .filter(Boolean);
    }

    function _stopNfRecoveryPolling() {
        if (_nfRecoveryPollTimer) {
            clearInterval(_nfRecoveryPollTimer);
            _nfRecoveryPollTimer = null;
        }
        _nfRecoveryPollAttempts = 0;
        _nfRecoverySeenAction = false;
    }

    function _setNfRecoveryFeedback(state) {
        var wrap = document.getElementById("nf-faltantes-feedback");
        var title = document.getElementById("nf-feedback-title");
        var count = document.getElementById("nf-feedback-count");
        var bar = document.getElementById("nf-feedback-bar");
        var note = document.getElementById("nf-feedback-note");
        if (!wrap || !title || !count || !bar || !note) return;
        if (!state || state.hidden) {
            wrap.className = "";
            wrap.style.display = "none";
            title.textContent = "";
            count.textContent = "";
            note.textContent = "";
            bar.className = "nf-progress-fill";
            bar.style.width = "0%";
            return;
        }
        var kind = String(state.kind || "active");
        var current = Math.max(0, Number(state.current || 0));
        var total = Math.max(0, Number(state.total || 0));
        var percent = total > 0 ? Math.max(0, Math.min(100, Math.round((current / total) * 100))) : 0;
        wrap.className = kind;
        wrap.classList.add("active");
        wrap.style.display = "block";
        title.textContent = _normalizeUiText(state.title || "Recuperando no Botana");
        count.textContent = total > 0 ? (current + "/" + total) : "";
        note.textContent = _normalizeUiText(String(state.note || "").trim());
        bar.className = "nf-progress-fill";
        if (kind === "error") {
            bar.classList.add("error");
            bar.style.width = percent > 0 ? (percent + "%") : "100%";
        } else if (kind === "success") {
            bar.classList.add("success");
            bar.style.width = "100%";
        } else if (kind === "loading" || total <= 0) {
            bar.classList.add("indeterminate");
            bar.style.width = "36%";
        } else {
            bar.style.width = percent + "%";
        }
    }

    async function _pollNfRecoveryState() {
        try {
            _nfRecoveryPollAttempts += 1;
            var res = await fetch("/botana/api/state");
            var data = await res.json();
            var action = (data && data.manual_action) || {};
            if (String(action.kind || "") !== "recover_missing") {
                if (!_nfRecoverySeenAction && _nfRecoveryPollAttempts <= 6) {
                    _setNfRecoveryFeedback({
                        kind: "loading",
                        title: "Enviando ao Botana",
                        note: "Aguardando o Botana iniciar a recuperação."
                    });
                    return;
                }
                _stopNfRecoveryPolling();
                _setNfRecoveryFeedback({
                    kind: "success",
                    title: "Recuperação enviada ao Botana",
                    note: "A solicitação foi entregue; acompanhe o andamento completo no painel do Botana."
                });
                return;
            }
            _nfRecoverySeenAction = true;
            var active = !!action.active;
            var phase = String(action.phase || "");
            var current = Math.max(0, Number(action.progress_current || 0));
            var total = Math.max(0, Number(action.progress_total || 0));
            if (active) {
                _setNfRecoveryFeedback({
                    kind: total > 0 ? "active" : "loading",
                    current: current,
                    total: total,
                    title: phase === "processing" ? "Lendo e-mails no Botana" : "Buscando e-mails no Botana",
                    note: total > 0 ? "Recuperação em andamento para as NFs selecionadas." : "Preparando a recuperação no Botana."
                });
                return;
            }
            _stopNfRecoveryPolling();
            if (String(action.status || "") === "error") {
                _setNfRecoveryFeedback({
                    kind: "error",
                    current: current,
                    total: total,
                    title: "Falha na recuperação",
                    note: _normalizeUiText(String(action.message || action.detail || "Não foi possível concluir a recuperação no Botana."))
                });
                return;
            }
            _setNfRecoveryFeedback({
                kind: "success",
                current: current || total,
                total: total,
                title: "Recuperação concluída",
                note: "O Botana terminou a busca das NFs selecionadas."
            });
        } catch (err) {
            _stopNfRecoveryPolling();
            _setNfRecoveryFeedback({
                kind: "error",
                title: "Erro ao acompanhar o Botana",
                note: "Não foi possível consultar o progresso da recuperação."
            });
        }
    }

    function _startNfRecoveryPolling() {
        _stopNfRecoveryPolling();
        _nfRecoveryPollAttempts = 0;
        _nfRecoverySeenAction = false;
        _nfRecoveryPollTimer = setInterval(function() {
            _pollNfRecoveryState();
        }, 1500);
        _pollNfRecoveryState();
    }

    function atualizarAcoesFaltantes() {
        var actionBox = document.getElementById("nf-faltantes-actions");
        var summaryEl = document.getElementById("nf-selection-summary");
        var btn = document.getElementById("btn-recuperar-faltantes");
        var toggle = document.getElementById("nf-select-all");
        var checks = _nfCheckboxes();
        var selected = _nfsFaltantesSelecionadas();
        var total = checks.length;
        if (actionBox) {
            actionBox.style.display = total > 0 ? "grid" : "none";
        }
        if (summaryEl) {
            summaryEl.textContent = total > 0
                ? (selected.length + " de " + total + " NF(s) selecionadas para recuperar no Botana.")
                : "Nenhuma NF faltante selecionada.";
        }
        if (btn) {
            btn.disabled = selected.length === 0;
            btn.textContent = "Recuperar NFs";
        }
        if (toggle) {
            toggle.checked = total > 0 && selected.length === total;
            toggle.indeterminate = selected.length > 0 && selected.length < total;
        }
    }

    function toggleSelecionarTodasFaltantes(source) {
        var mark = !!(source && source.checked);
        _nfCheckboxes().forEach(function(el) { el.checked = mark; });
        atualizarAcoesFaltantes();
    }

    async function recuperarFaltantesSelecionadas() {
        var selecionadas = _nfsFaltantesSelecionadas();
        var btn = document.getElementById("btn-recuperar-faltantes");
        if (!selecionadas.length) {
            _setNfRecoveryFeedback({
                kind: "error",
                title: "Nenhuma NF selecionada",
                note: "Selecione ao menos uma NF faltante para enviar ao Botana."
            });
            atualizarAcoesFaltantes();
            return;
        }
        var quantidade = selecionadas.length;
        var confirmMsg = quantidade === 1
            ? ("Enviar a NF " + selecionadas[0] + " para Recuperar e-mails no Botana?")
            : ("Enviar " + quantidade + " NFs faltantes para Recuperar e-mails no Botana?");
        if (!window.confirm(confirmMsg)) {
            return;
        }
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Enviando...";
        }
        _setNfRecoveryFeedback({
            kind: "loading",
            title: "Enviando ao Botana",
            note: "Preparando a recuperação das NFs selecionadas."
        });
        try {
            var resposta = await fetch("/botana/api/recover-emails", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mode: "list",
                    nf_list: selecionadas,
                    max_messages: 1000
                })
            });
            var dados = await resposta.json().catch(function() { return {}; });
            if (resposta.ok && dados.ok) {
                fecharLoginBotana();
                _startNfRecoveryPolling();
            } else {
                var failMsg = _normalizeUiText(String(dados.message || "Nao foi possivel iniciar a recuperacao no Botana."));
                if (_isBotanaAuthError(resposta.status, failMsg)) {
                    mostrarLoginBotana(failMsg);
                }
                _setNfRecoveryFeedback({
                    kind: "error",
                    title: "Falha ao iniciar",
                    note: failMsg
                });
            }
        } catch (err) {
            _setNfRecoveryFeedback({
                kind: "error",
                title: "Erro de rede",
                note: _normalizeUiText("Erro de rede ao chamar o Botana: " + err)
            });
        } finally {
            atualizarAcoesFaltantes();
        }
    }

    function mudarFiltro() {
        const tipo = document.getElementById("filtro-tipo").value;
        document.getElementById("div-mes").style.display = (tipo === "mes") ? "block" : "none";
        document.getElementById("div-nfs").style.display = (tipo === "nfs") ? "grid" : "none";
    }

    function _camposRelatorioVisiveis() {
        var campos = [
            document.getElementById("filtro-empresa"),
            document.getElementById("filtro-tipo")
        ];
        var tipo = document.getElementById("filtro-tipo").value;
        if (tipo === "mes") {
            campos.push(document.getElementById("input-mes"));
        } else if (tipo === "nfs") {
            campos.push(document.getElementById("input-nf-inicio"));
            campos.push(document.getElementById("input-nf-fim"));
        }
        campos.push(document.getElementById("btn-gerar-relatorio"));
        return campos.filter(function(el) {
            return !!el && !el.disabled && el.offsetParent !== null;
        });
    }

    function _focarProximoCampoRelatorio(atual) {
        var campos = _camposRelatorioVisiveis();
        var idx = campos.indexOf(atual);
        if (idx === -1) return;
        var proximo = campos[idx + 1];
        if (!proximo) return;
        proximo.focus();
        if (typeof proximo.select === "function" && proximo.tagName === "INPUT") {
            proximo.select();
        }
    }

    function _atalhoEnterRelatorio(event) {
        if (event.key !== "Enter") return;
        var alvo = event.target;
        if (!alvo || alvo.id === "btn-baixar-csv") return;
        event.preventDefault();
        if (alvo.id === "btn-gerar-relatorio") {
            gerarRelatorio();
            return;
        }
        _focarProximoCampoRelatorio(alvo);
    }

    function configurarAtalhosRelatorio() {
        [
            "filtro-empresa",
            "filtro-tipo",
            "input-mes",
            "input-nf-inicio",
            "input-nf-fim",
            "btn-gerar-relatorio"
        ].forEach(function(id) {
            var el = document.getElementById(id);
            if (!el || el.dataset.enterBound === "1") return;
            el.dataset.enterBound = "1";
            el.addEventListener("keydown", _atalhoEnterRelatorio);
        });
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
        _stopNfRecoveryPolling();
        _setNfRecoveryFeedback({ hidden: true });

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
                var nf = String(faltantes[idx].NF || "").trim();
                tr.innerHTML =
                    '<td class="nf-select-cell" style="padding: 8px; border: 1px solid #ddd;"><input class="nf-faltante-check" type="checkbox" value="' + nf + '" onchange="atualizarAcoesFaltantes()"></td>' +
                    '<td style="padding: 8px; border: 1px solid #ddd;">' + (idx + 1) + '</td>' +
                    '<td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; color: #c0392b;">' + nf + '</td>';
                tbody.appendChild(tr);
            }
            container.style.display = "block";
            document.getElementById("btn-baixar-csv").style.display = "inline-block";
        } else {
            container.style.display = "none";
            document.getElementById("btn-baixar-csv").style.display = "none";
        }
        atualizarAcoesFaltantes();
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

    mudarFiltro();
    configurarAtalhosRelatorio();

    var pollingCorrecaoTimer = null;
    var pollingCorrecaoDesde = 0;

    function iniciarCorrecao() {
      var empresaSelecionada = document.getElementById("correcao-empresa").value;
      var abaFiltro = document.getElementById("correcao-aba").value.trim();
      var btn = document.getElementById("btn-corrigir");
      var logContainer = document.getElementById("correcao-log-container");

      btn.innerText = "Processando...";
      btn.disabled = true;
      btn.style.background = "#9cdaf8";
      logContainer.innerHTML = "";
      logContainer.style.display = "block";
      pollingCorrecaoDesde = 0;

      fetch("/botana/api/clean-sheets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ empresa: empresaSelecionada, aba: abaFiltro })
      })
      .then(function(res) { return res.json().then(function(d) { return [res.ok, d]; }); })
      .then(function(arr) {
        var ok = arr[0]; var dados = arr[1];
        if (ok && dados.ok) {
          adicionarLinhaLog("info", dados.friendly || "Correção iniciada.");
          iniciarPollingLog();
        } else {
          adicionarLinhaLog("erro", dados.friendly || dados.message || "Erro ao iniciar.");
          btn.innerText = "Iniciar Correção";
          btn.disabled = false;
          btn.style.background = "#176fe5";
        }
      })
      .catch(function(err) {
        adicionarLinhaLog("erro", "Erro de rede: " + err);
        btn.innerText = "Iniciar Correção";
        btn.disabled = false;
        btn.style.background = "#176fe5";
      });
    }

    function iniciarPollingLog() {
      if (pollingCorrecaoTimer) clearInterval(pollingCorrecaoTimer);
      pollingCorrecaoTimer = setInterval(function() { buscarLog(); }, 2000);
      buscarLog();
    }

    function buscarLog() {
      fetch("/botana/api/clean-sheets/log?desde=" + pollingCorrecaoDesde)
        .then(function(res) { return res.json(); })
        .then(function(data) {
          if (data.ok) {
            var entradas = data.entries || [];
            for (var i = 0; i < entradas.length; i++) {
              adicionarLinhaLog(entradas[i].tipo, "[" + entradas[i].ts + "] " + entradas[i].msg);
            }
            pollingCorrecaoDesde = data.total || 0;

            if (!data.ativo && entradas.length === 0) {
              clearInterval(pollingCorrecaoTimer);
              pollingCorrecaoTimer = null;
              var btn = document.getElementById("btn-corrigir");
              btn.innerText = "Iniciar Correção";
              btn.disabled = false;
              btn.style.background = "#176fe5";
              adicionarLinhaLog("info", "--- Processo finalizado ---");
            }
          }
        })
        .catch(function() {});
    }

    function adicionarLinhaLog(tipo, msg) {
      var logContainer = document.getElementById("correcao-log-container");
      var linha = document.createElement("div");
      var cor = "#cdd6f4";
      if (tipo === "correcao") cor = "#f9e2af";
      if (tipo === "erro") cor = "#f38ba8";
      if (tipo === "info") cor = "#a6e3a1";
      linha.style.color = cor;
      linha.textContent = msg;
      logContainer.appendChild(linha);
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  </script>
</body>
</html>"""
