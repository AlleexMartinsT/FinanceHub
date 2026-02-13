from __future__ import annotations

import json
from pathlib import Path

from instances.models import AppConfig, InstanceConfig


class AppSettingsStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "instances.json"

    def _default(self) -> AppConfig:
        return AppConfig(
            panel_host="0.0.0.0",
            panel_port=8877,
            financeiro_panel_url="http://127.0.0.1:8765",
            anabot_panel_url="http://127.0.0.1:8865",
            financeiro_app_dir=r"C:\Users\vendas\Desktop\financeiroAPP",
            anabot_app_dir=r"C:\Users\vendas\Desktop\anaBot",
            auto_update_enabled=True,
            auto_update_interval_minutes=5,
            auto_update_remote="origin",
            auto_update_branch="main",
            instances=[
                InstanceConfig(
                    instance_id="financeiro_principal",
                    display_name="Financeiro Principal",
                    instance_type="financeiro",
                    enabled=True,
                    interval_seconds=1800,
                    credentials_key="financeiro_principal",
                    notes="Instancia base do FinanceiroAPP",
                ),
                InstanceConfig(
                    instance_id="anabot_principal",
                    display_name="AnaBot Principal",
                    instance_type="anabot",
                    enabled=False,
                    interval_seconds=1800,
                    credentials_key="anabot_principal",
                    notes="Instancia base do anaBot",
                ),
            ],
        )

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = self._default()
            self.save(cfg)
            return cfg

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            cfg = self._default()
            self.save(cfg)
            return cfg

        panel_host = str(raw.get("panel_host", "0.0.0.0")).strip() or "0.0.0.0"
        try:
            panel_port = max(1024, min(65535, int(raw.get("panel_port", 8877))))
        except Exception:
            panel_port = 8877
        financeiro_panel_url = str(raw.get("financeiro_panel_url", "http://127.0.0.1:8765")).strip() or "http://127.0.0.1:8765"
        anabot_panel_url = str(raw.get("anabot_panel_url", "http://127.0.0.1:8865")).strip() or "http://127.0.0.1:8865"
        if anabot_panel_url.endswith("/anabot"):
            anabot_panel_url = "http://127.0.0.1:8865"
        financeiro_app_dir = str(raw.get("financeiro_app_dir", r"C:\Users\vendas\Desktop\financeiroAPP")).strip() or r"C:\Users\vendas\Desktop\financeiroAPP"
        anabot_app_dir = str(raw.get("anabot_app_dir", r"C:\Users\vendas\Desktop\anaBot")).strip() or r"C:\Users\vendas\Desktop\anaBot"
        auto_update_enabled = bool(raw.get("auto_update_enabled", True))
        try:
            auto_update_interval_minutes = max(1, min(720, int(raw.get("auto_update_interval_minutes", 5))))
        except Exception:
            auto_update_interval_minutes = 5
        auto_update_remote = str(raw.get("auto_update_remote", "origin")).strip() or "origin"
        auto_update_branch = str(raw.get("auto_update_branch", "main")).strip() or "main"

        instances = []
        for item in raw.get("instances", []):
            try:
                cfg = InstanceConfig(
                    instance_id=str(item.get("instance_id", "")).strip(),
                    display_name=str(item.get("display_name", "")).strip(),
                    instance_type=str(item.get("instance_type", "")).strip().lower(),
                    enabled=bool(item.get("enabled", True)),
                    interval_seconds=int(item.get("interval_seconds", 1800)),
                    credentials_key=str(item.get("credentials_key", "")).strip(),
                    notes=str(item.get("notes", "")).strip(),
                ).sanitize()
                instances.append(cfg)
            except Exception:
                continue

        if not instances:
            instances = self._default().instances

        cfg = AppConfig(
            panel_host=panel_host,
            panel_port=panel_port,
            financeiro_panel_url=financeiro_panel_url,
            anabot_panel_url=anabot_panel_url,
            financeiro_app_dir=financeiro_app_dir,
            anabot_app_dir=anabot_app_dir,
            auto_update_enabled=auto_update_enabled,
            auto_update_interval_minutes=auto_update_interval_minutes,
            auto_update_remote=auto_update_remote,
            auto_update_branch=auto_update_branch,
            instances=instances,
        )
        self.save(cfg)
        return cfg

    def save(self, config: AppConfig) -> None:
        out = {
            "panel_host": config.panel_host,
            "panel_port": int(config.panel_port),
            "financeiro_panel_url": str(config.financeiro_panel_url or "").strip(),
            "anabot_panel_url": str(config.anabot_panel_url or "").strip(),
            "financeiro_app_dir": str(config.financeiro_app_dir or "").strip(),
            "anabot_app_dir": str(config.anabot_app_dir or "").strip(),
            "auto_update_enabled": bool(config.auto_update_enabled),
            "auto_update_interval_minutes": int(config.auto_update_interval_minutes),
            "auto_update_remote": str(config.auto_update_remote or "").strip(),
            "auto_update_branch": str(config.auto_update_branch or "").strip(),
            "instances": [
                {
                    "instance_id": i.instance_id,
                    "display_name": i.display_name,
                    "instance_type": i.instance_type,
                    "enabled": bool(i.enabled),
                    "interval_seconds": int(i.interval_seconds),
                    "credentials_key": i.credentials_key,
                    "notes": i.notes,
                }
                for i in config.instances
            ],
        }
        self.path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
