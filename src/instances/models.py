from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


VALID_INSTANCE_TYPES = {"financeiro", "anabot"}
VALID_STATUS = {"idle", "running", "stopped", "error"}


@dataclass
class InstanceConfig:
    instance_id: str
    display_name: str
    instance_type: str
    enabled: bool = True
    interval_seconds: int = 1800
    credentials_key: str = ""
    notes: str = ""

    def sanitize(self) -> "InstanceConfig":
        if not self.instance_id:
            raise ValueError("instance_id obrigatorio")
        if self.instance_type not in VALID_INSTANCE_TYPES:
            raise ValueError(f"instance_type invalido: {self.instance_type}")
        self.interval_seconds = max(30, min(86400, int(self.interval_seconds)))
        self.display_name = self.display_name or self.instance_id
        self.credentials_key = str(self.credentials_key or "").strip()
        self.notes = str(self.notes or "").strip()
        return self


@dataclass
class RuntimeState:
    status: str = "idle"
    detail: str = "Aguardando"
    last_started_at: str = ""
    last_finished_at: str = ""
    next_run_in_seconds: int | None = None
    runs_ok: int = 0
    runs_error: int = 0
    current_run_manual: bool = False
    stop_requested: bool = False
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def set_status(self, status: str, detail: str) -> None:
        if status not in VALID_STATUS:
            status = "error"
        self.status = status
        self.detail = detail
        self.updated_at = datetime.now().isoformat(timespec="seconds")


@dataclass
class AppConfig:
    panel_host: str = "0.0.0.0"
    panel_port: int = 8877
    financeiro_panel_url: str = "http://127.0.0.1:8765"
    anabot_panel_url: str = "http://127.0.0.1:8865"
    financeiro_app_dir: str = r"C:\Users\vendas\Desktop\financeiroAPP"
    anabot_app_dir: str = r"C:\Users\vendas\Desktop\anaBot"
    auto_update_enabled: bool = True
    auto_update_interval_minutes: int = 5
    auto_update_remote: str = "origin"
    auto_update_branch: str = "main"
    instances: list[InstanceConfig] = field(default_factory=list)
