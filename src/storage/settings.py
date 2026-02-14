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
                    backend_url="http://127.0.0.1:8765",
                    app_dir=r"C:\FinanceBot",
                    start_args=["main.py", "--server", "--no-browser"],
                    route_prefix="financeiro",
                    repo_url="https://github.com/AlleexMartinsT/financeiroBot.git",
                    repo_branch="main",
                    auto_clone_missing=True,
                    credentials_key="financeiro_principal",
                    notes="Instancia base do FinanceiroAPP",
                ).sanitize(),
                InstanceConfig(
                    instance_id="anabot_principal",
                    display_name="AnaBot Principal",
                    instance_type="anabot",
                    enabled=True,
                    interval_seconds=1800,
                    backend_url="http://127.0.0.1:8865",
                    app_dir=r"C:\AnaBot",
                    start_args=["main.py", "--server", "--host", "127.0.0.1", "--port", "8865"],
                    route_prefix="anabot",
                    repo_url="https://github.com/AlleexMartinsT/Botana.git",
                    repo_branch="main",
                    auto_clone_missing=True,
                    credentials_key="anabot_principal",
                    notes="Instancia base do anaBot",
                ).sanitize(),
            ],
        )

    @staticmethod
    def _legacy_defaults(raw: dict) -> dict:
        return {
            "financeiro_url": str(raw.get("financeiro_panel_url", "http://127.0.0.1:8765")).strip() or "http://127.0.0.1:8765",
            "anabot_url": str(raw.get("anabot_panel_url", "http://127.0.0.1:8865")).strip() or "http://127.0.0.1:8865",
            "financeiro_dir": str(raw.get("financeiro_app_dir", r"C:\FinanceBot")).strip() or r"C:\FinanceBot",
            "anabot_dir": str(raw.get("anabot_app_dir", r"C:\AnaBot")).strip() or r"C:\AnaBot",
        }

    @staticmethod
    def _default_start_args(instance_type: str) -> list[str]:
        if instance_type == "financeiro":
            return ["main.py", "--server", "--no-browser"]
        if instance_type == "anabot":
            return ["main.py", "--server", "--host", "127.0.0.1", "--port", "8865"]
        return ["main.py", "--server"]

    def _parse_instance(self, item: dict, legacy: dict) -> InstanceConfig:
        inst_type = str(item.get("instance_type", "")).strip().lower()
        if inst_type == "financeiro":
            backend_default = legacy["financeiro_url"]
            app_default = legacy["financeiro_dir"]
            prefix_default = "financeiro"
            repo_default = "https://github.com/AlleexMartinsT/financeiroBot.git"
        elif inst_type == "anabot":
            backend_default = legacy["anabot_url"]
            app_default = legacy["anabot_dir"]
            prefix_default = "anabot"
            repo_default = "https://github.com/AlleexMartinsT/Botana.git"
        else:
            backend_default = ""
            app_default = ""
            prefix_default = str(item.get("instance_id", "")).strip() or "instancia"
            repo_default = ""

        start_args = item.get("start_args")
        if not isinstance(start_args, list):
            start_args = self._default_start_args(inst_type)
        if inst_type == "anabot":
            clean_args = [str(x).strip() for x in start_args if str(x).strip()]
            if "--no-browser" in clean_args:
                clean_args = [x for x in clean_args if x != "--no-browser"]
            if "--server" not in clean_args:
                clean_args.insert(0, "--server")
                clean_args.insert(0, "main.py")
            if not clean_args:
                clean_args = self._default_start_args(inst_type)
            start_args = clean_args

        raw_repo_url = str(item.get("repo_url", "")).strip()
        repo_url = raw_repo_url or repo_default

        raw_auto_clone = item.get("auto_clone_missing", None)
        auto_clone_default = inst_type in {"financeiro", "anabot"}
        if raw_auto_clone is None:
            auto_clone_missing = auto_clone_default
        else:
            auto_clone_missing = bool(raw_auto_clone)
            # Migração de configs antigas do anabot: sem repo_url e clone desativado.
            if inst_type == "anabot" and not raw_repo_url:
                auto_clone_missing = True

        cfg = InstanceConfig(
            instance_id=str(item.get("instance_id", "")).strip(),
            display_name=str(item.get("display_name", "")).strip(),
            instance_type=inst_type,
            enabled=bool(item.get("enabled", True)),
            interval_seconds=int(item.get("interval_seconds", 1800)),
            backend_url=str(item.get("backend_url", backend_default)).strip() or backend_default,
            app_dir=str(item.get("app_dir", app_default)).strip() or app_default,
            start_args=[str(x) for x in start_args],
            route_prefix=str(item.get("route_prefix", prefix_default)).strip() or prefix_default,
            repo_url=repo_url,
            repo_branch=str(item.get("repo_branch", "main")).strip() or "main",
            auto_clone_missing=auto_clone_missing,
            credentials_key=str(item.get("credentials_key", "")).strip(),
            notes=str(item.get("notes", "")).strip(),
        ).sanitize()
        return cfg

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

        auto_update_enabled = bool(raw.get("auto_update_enabled", True))
        try:
            auto_update_interval_minutes = max(1, min(720, int(raw.get("auto_update_interval_minutes", 5))))
        except Exception:
            auto_update_interval_minutes = 5
        auto_update_remote = str(raw.get("auto_update_remote", "origin")).strip() or "origin"
        auto_update_branch = str(raw.get("auto_update_branch", "main")).strip() or "main"

        legacy = self._legacy_defaults(raw)
        if legacy["anabot_url"].endswith("/anabot"):
            legacy["anabot_url"] = "http://127.0.0.1:8865"

        instances = []
        for item in raw.get("instances", []):
            try:
                if not isinstance(item, dict):
                    continue
                instances.append(self._parse_instance(item, legacy))
            except Exception:
                continue

        if not instances:
            instances = self._default().instances

        cfg = AppConfig(
            panel_host=panel_host,
            panel_port=panel_port,
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
                    "backend_url": i.backend_url,
                    "app_dir": i.app_dir,
                    "start_args": list(i.start_args or []),
                    "route_prefix": i.route_prefix,
                    "repo_url": i.repo_url,
                    "repo_branch": i.repo_branch,
                    "auto_clone_missing": bool(i.auto_clone_missing),
                    "credentials_key": i.credentials_key,
                    "notes": i.notes,
                }
                for i in config.instances
            ],
        }
        self.path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
