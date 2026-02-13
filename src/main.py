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
    fin_dir = Path(str(config.financeiro_app_dir))
    ana_dir = Path(str(config.anabot_app_dir))
    fin_main = fin_dir / "main.py"
    ana_main = ana_dir / "main.py"
    print(f"[Sync] Financeiro URL: {config.financeiro_panel_url}")
    print(f"[Sync] Financeiro dir: {fin_dir} | main.py={'OK' if fin_main.exists() else 'FALTA'}")
    print(f"[Sync] AnaBot URL: {config.anabot_panel_url}")
    print(f"[Sync] AnaBot dir: {ana_dir} | main.py={'OK' if ana_main.exists() else 'FALTA'}")


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
