from pathlib import Path
import os
import subprocess
import time
import sys

from auto_updater import AutoUpdater
from core.runtime import InstanceRuntimeManager
from storage.settings import AppSettingsStore
from web.server import HubHttpServer


def _current_commit(base_dir: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(base_dir),
            text=True,
            capture_output=True,
            check=False,
        )
        out = (proc.stdout or "").strip()
        return out if out else "-"
    except Exception:
        return "-"


def _restart_process(base_dir: Path):
    print("[Hub Updater] Reiniciando processo do HUB")
    # Reinicio explicito do entrypoint evita cair em modo interativo.
    entrypoint = Path(__file__).resolve()
    args = [sys.executable, str(entrypoint)]
    env = os.environ.copy()
    try:
        env["HUB_UPDATE_COUNT"] = str(int(env.get("HUB_UPDATE_COUNT", "0")) + 1)
    except Exception:
        env["HUB_UPDATE_COUNT"] = "1"
    subprocess.Popen(args, cwd=str(base_dir), env=env)
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
    # Limpa a tela a cada start (inclusive apos auto-update/restart).
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass
    settings = AppSettingsStore(base_dir=base_dir)
    config = settings.load()
    try:
        update_count = int(os.environ.get("HUB_UPDATE_COUNT", "0"))
    except Exception:
        update_count = 0
    commit = _current_commit(base_dir)
    print(f"[Hub] Build: {commit} | Auto-update restarts in this CMD: {update_count}")
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
    server.start_instance_updater(
        enabled=bool(config.auto_update_enabled),
        interval_minutes=int(config.auto_update_interval_minutes),
    )
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
