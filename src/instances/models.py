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
    backend_url: str = ""
    app_dir: str = ""
    start_args: list[str] = field(default_factory=list)
    route_prefix: str = ""
    repo_url: str = ""
    repo_branch: str = "main"
    auto_clone_missing: bool = False
    credentials_key: str = ""
    notes: str = ""

    def sanitize(self) -> "InstanceConfig":
        if not self.instance_id:
            raise ValueError("instance_id obrigatorio")
        self.instance_type = str(self.instance_type or "").strip().lower()
        if self.instance_type not in VALID_INSTANCE_TYPES:
            raise ValueError(f"instance_type invalido: {self.instance_type}")
        self.interval_seconds = max(30, min(86400, int(self.interval_seconds)))
        self.display_name = self.display_name or self.instance_id
        self.backend_url = str(self.backend_url or "").strip()
        self.app_dir = str(self.app_dir or "").strip()
        self.start_args = [str(x).strip() for x in (self.start_args or []) if str(x).strip()]
        rp = str(self.route_prefix or self.instance_id).strip().strip("/")
        rp = rp.replace("\\", "/")
        if not rp:
            rp = self.instance_id
        self.route_prefix = rp
        self.repo_url = str(self.repo_url or "").strip()
        self.repo_branch = str(self.repo_branch or "main").strip() or "main"
        self.auto_clone_missing = bool(self.auto_clone_missing)
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
    auto_update_enabled: bool = True
    auto_update_interval_minutes: int = 5
    auto_update_remote: str = "origin"
    auto_update_branch: str = "main"
    instances: list[InstanceConfig] = field(default_factory=list)
