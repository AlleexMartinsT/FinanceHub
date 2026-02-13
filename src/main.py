from pathlib import Path
import os
import subprocess
import time
import sys

from auto_updater import AutoUpdater
from core.runtime import InstanceRuntimeManager
from storage.settings import AppSettingsStore
from web.server import HubHttpServer


def _restart_process(base_dir: Path):
    print("[Hub Updater] Reiniciando processo do HUB")
    args = [sys.executable] + sys.argv
    subprocess.Popen(args, cwd=str(base_dir))
    os._exit(0)


def _check_sync(config) -> None:
    for inst in config.instances:
        app_dir = Path(str(inst.app_dir or ""))
        main_file = app_dir / "main.py"
        print(f"[Sync] {inst.display_name} ({inst.route_prefix})")
        print(f"[Sync] URL: {inst.backend_url}")
        print(f"[Sync] Dir: {app_dir} | main.py={'OK' if main_file.exists() else 'FALTA'}")


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    settings = AppSettingsStore(base_dir=base_dir)
    config = settings.load()
    _check_sync(config)

    runtime = InstanceRuntimeManager(instances=config.instances)
    server = HubHttpServer(
        host=config.panel_host,
        port=config.panel_port,
        runtime=runtime,
        settings=settings,
    )
    updater = AutoUpdater(
        repo_dir=base_dir,
        enabled=bool(config.auto_update_enabled),
        interval_minutes=int(config.auto_update_interval_minutes),
        remote=str(config.auto_update_remote),
        branch=str(config.auto_update_branch),
    )
    updater.start()
    server.start()
    server.warm_up_enabled_backends()
    print(f"FinanceAnaHub online em http://{config.panel_host}:{config.panel_port}")
    print("Ctrl+C para encerrar")
    try:
        while True:
            time.sleep(1)
            if updater.consume_restart_request():
                runtime.stop_all()
                server.stop()
                updater.stop()
                _restart_process(base_dir)
    except KeyboardInterrupt:
        print("\nEncerrando...")
        runtime.stop_all()
        server.stop()
        updater.stop()


if __name__ == "__main__":
    main()
