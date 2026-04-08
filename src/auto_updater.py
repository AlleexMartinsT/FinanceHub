from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path


class AutoUpdater:
    def __init__(
        self,
        repo_dir: str | Path,
        enabled: bool = True,
        interval_minutes: int = 5,
        remote: str = "origin",
        branch: str = "main",
        event_callback=None,
    ):
        self.repo_dir = Path(repo_dir).resolve()
        self.enabled = bool(enabled)
        self.interval_minutes = max(1, int(interval_minutes))
        self.remote = (remote or "origin").strip()
        self.branch = (branch or "main").strip()
        self._event_callback = event_callback
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._restart_requested = threading.Event()
        self._thread = None
        self._checked_env = False
        self._available = False
        self._next_check_at = 0.0

    def _emit(self, message: str) -> None:
        msg = str(message or "").strip()
        if not msg:
            return
        callback = self._event_callback
        if callable(callback):
            try:
                callback(msg)
                return
            except Exception:
                pass
        print(msg)

    def _check_env(self) -> bool:
        if self._checked_env:
            return self._available
        self._checked_env = True
        if not self.enabled:
            self._available = False
            return False
        if shutil.which("git") is None:
            self._emit("[Hub Updater] Git nao encontrado. Auto-update desativado")
            self._available = False
            return False
        if not (self.repo_dir / ".git").exists():
            self._emit("[Hub Updater] Repo git nao encontrado no HUB. Auto-update desativado")
            self._available = False
            return False
        self._available = True
        return True

    def _run_git(self, *args: str) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_dir),
                text=True,
                capture_output=True,
                check=False,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode, out
        except Exception as e:
            return 1, str(e)

    def _head(self) -> str:
        code, out = self._run_git("rev-parse", "HEAD")
        return out if code == 0 else ""

    def _remote_head(self) -> str:
        ref = f"{self.remote}/{self.branch}"
        code, out = self._run_git("rev-parse", ref)
        return out if code == 0 else ""

    def _update_once(self):
        code, out = self._run_git("fetch", self.remote, self.branch)
        if code != 0:
            if out:
                self._emit(f"[Hub Updater] Falha no fetch: {out}")
            return

        local_head = self._head()
        remote_head = self._remote_head()
        if not local_head or not remote_head or local_head == remote_head:
            return

        self._emit(f"[Hub Updater] Nova versao detectada ({local_head[:7]} -> {remote_head[:7]})")
        code, out = self._run_git("pull", "--ff-only", self.remote, self.branch)
        if code != 0:
            if out:
                self._emit(f"[Hub Updater] Falha no pull: {out}")
            return

        new_head = self._head()
        if new_head and new_head != local_head:
            self._emit(f"[Hub Updater] Atualizacao aplicada para {new_head[:7]}. Reinicio solicitado")
            self._restart_requested.set()

    def _loop(self):
        self._emit(
            "[Hub Updater] Ativo: "
            f"repo={self.repo_dir} remote={self.remote} branch={self.branch} "
            f"intervalo={self.interval_minutes}min"
        )
        self._next_check_at = time.time()
        while not self._stop.is_set():
            timeout = max(0.0, self._next_check_at - time.time())
            self._wake.wait(timeout=timeout)
            if self._stop.is_set():
                self._next_check_at = 0.0
                return
            self._wake.clear()
            self._update_once()
            self._next_check_at = time.time() + (self.interval_minutes * 60)

    def start(self):
        if not self._check_env():
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # Forca checagem imediata no startup.
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._next_check_at = 0.0

    def trigger_check(self, reason: str = "manual") -> bool:
        if not self._check_env():
            return False
        self._next_check_at = time.time()
        self._wake.set()
        try:
            self._emit(f"[Hub Updater] Checagem imediata solicitada ({reason})")
        except Exception:
            pass
        return True

    def consume_restart_request(self) -> bool:
        if self._restart_requested.is_set():
            self._restart_requested.clear()
            return True
        return False

    def get_console_state(self) -> dict:
        next_at = float(self._next_check_at or 0.0)
        remaining = max(0, int(next_at - time.time())) if next_at > 0 else 0
        return {
            "enabled": bool(self.enabled),
            "available": bool(self._available),
            "interval_minutes": int(self.interval_minutes),
            "next_check_at": next_at,
            "next_check_in_seconds": remaining,
            "remote": self.remote,
            "branch": self.branch,
        }
