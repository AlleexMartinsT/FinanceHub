from __future__ import annotations

import threading
import time
from datetime import datetime

from instances.models import InstanceConfig, RuntimeState


class InstanceWorker:
    def __init__(self, config: InstanceConfig):
        self.config = config.sanitize()
        self.state = RuntimeState()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"inst-{self.config.instance_id}")

    def start(self) -> None:
        with self._lock:
            if not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True, name=f"inst-{self.config.instance_id}")
                self._stop_event.clear()
                self._wake_event.clear()
                self._thread.start()
            self.state.set_status("idle", "Aguardando proximo ciclo")

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self.state.stop_requested = True
        self.state.set_status("stopped", "Parada solicitada")

    def run_now(self) -> None:
        self._wake_event.set()

    def snapshot(self) -> dict:
        return {
            "instance_id": self.config.instance_id,
            "display_name": self.config.display_name,
            "instance_type": self.config.instance_type,
            "route_prefix": self.config.route_prefix,
            "backend_url": self.config.backend_url,
            "app_dir": self.config.app_dir,
            "start_args": list(self.config.start_args or []),
            "enabled": self.config.enabled,
            "interval_seconds": self.config.interval_seconds,
            "credentials_key": self.config.credentials_key,
            "notes": self.config.notes,
            "state": {
                "status": self.state.status,
                "detail": self.state.detail,
                "last_started_at": self.state.last_started_at,
                "last_finished_at": self.state.last_finished_at,
                "next_run_in_seconds": self.state.next_run_in_seconds,
                "runs_ok": self.state.runs_ok,
                "runs_error": self.state.runs_error,
                "current_run_manual": self.state.current_run_manual,
                "stop_requested": self.state.stop_requested,
                "updated_at": self.state.updated_at,
            },
        }

    def _execute_cycle(self, manual: bool) -> None:
        self.state.current_run_manual = manual
        self.state.last_started_at = datetime.now().isoformat(timespec="seconds")
        self.state.set_status("running", "Executando ciclo")
        try:
            # Placeholder da Fase 1: aqui sera acoplado adapter financeiro/anabot.
            time.sleep(1)
            self.state.runs_ok += 1
            self.state.set_status("idle", "Ciclo finalizado com sucesso")
        except Exception as exc:
            self.state.runs_error += 1
            self.state.set_status("error", f"Falha no ciclo: {exc}")
        finally:
            self.state.current_run_manual = False
            self.state.last_finished_at = datetime.now().isoformat(timespec="seconds")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if not self.config.enabled:
                self.state.next_run_in_seconds = None
                self.state.set_status("stopped", "Instancia desativada")
                time.sleep(1)
                continue

            manual = self._wake_event.is_set()
            if manual:
                self._wake_event.clear()
            self._execute_cycle(manual=manual)

            remaining = self.config.interval_seconds
            while remaining > 0 and not self._stop_event.is_set():
                if self._wake_event.is_set():
                    break
                self.state.next_run_in_seconds = remaining
                time.sleep(1)
                remaining -= 1
            self.state.next_run_in_seconds = 0


class InstanceRuntimeManager:
    def __init__(self, instances: list[InstanceConfig]):
        self._workers = {cfg.instance_id: InstanceWorker(cfg) for cfg in instances}
        for worker in self._workers.values():
            worker.start()

    def list(self) -> list[dict]:
        return [w.snapshot() for w in self._workers.values()]

    def run_now(self, instance_id: str) -> bool:
        worker = self._workers.get(instance_id)
        if not worker:
            return False
        worker.run_now()
        return True

    def stop_instance(self, instance_id: str) -> bool:
        worker = self._workers.get(instance_id)
        if not worker:
            return False
        worker.stop()
        return True

    def stop_all(self) -> None:
        for worker in self._workers.values():
            worker.stop()
