from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time

try:
    import msvcrt  # type: ignore
except Exception:
    msvcrt = None

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


def _collect_sync_rows(config) -> list[dict]:
    rows = []
    for inst in config.instances:
        app_dir = Path(str(inst.app_dir or ""))
        main_file = app_dir / "main.py"
        rows.append(
            {
                "display_name": inst.display_name,
                "route_prefix": inst.route_prefix,
                "backend_url": inst.backend_url,
                "app_dir": str(app_dir),
                "enabled": bool(inst.enabled),
                "dir_exists": app_dir.exists(),
                "main_exists": main_file.exists(),
            }
        )
    return rows


def _format_countdown(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_next_check(timestamp: float) -> str:
    value = float(timestamp or 0.0)
    if value <= 0:
        return "aguardando agenda"
    return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M:%S")


def _read_console_shortcut() -> str:
    if msvcrt is None:
        return ""
    try:
        if not msvcrt.kbhit():
            return ""
        key = msvcrt.getwch()
    except Exception:
        return ""
    if key in ("\x00", "\xe0"):
        try:
            msvcrt.getwch()
        except Exception:
            pass
        return ""
    return str(key or "").strip().lower()


class ConsoleHud:
    def __init__(self):
        self._events = deque(maxlen=10)
        self._lock = threading.Lock()
        self._enable_ansi_on_windows()

    @staticmethod
    def _enable_ansi_on_windows() -> None:
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    def add_event(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        if not text.startswith("[20"):
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            text = f"[{stamp}] {text}"
        with self._lock:
            self._events.append(text)

    def _events_snapshot(self) -> list[str]:
        with self._lock:
            return list(self._events)

    @staticmethod
    def _box(title: str, rows: list[str], width: int) -> str:
        inner = max(32, int(width) - 4)
        cap = "+" + "-" * (inner + 2) + "+"
        out = [cap, f"| {str(title or '').strip()[:inner].ljust(inner)} |", cap]
        for raw in rows or [""]:
            chunks = textwrap.wrap(
                str(raw or "").strip(),
                width=inner,
                replace_whitespace=False,
                drop_whitespace=False,
            ) or [""]
            for chunk in chunks:
                out.append(f"| {chunk[:inner].ljust(inner)} |")
        out.append(cap)
        return "\n".join(out)

    @staticmethod
    def _render_screen(text: str) -> None:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(text.rstrip() + "\n")
        sys.stdout.flush()

    def render(
        self,
        *,
        commit: str,
        update_count: int,
        config,
        sync_rows: list[dict],
        updater_state: dict,
        server_state: dict,
    ) -> None:
        width = max(96, min(shutil.get_terminal_size((120, 40)).columns, 140))
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        hub_url = f"http://{server_state.get('host', config.panel_host)}:{server_state.get('port', config.panel_port)}"
        recent_events = self._events_snapshot()[-8:]

        header_rows = [
            r"  ______ _                             _                  _   _       _     ",
            r" |  ____(_)                           | |                | | | |     | |    ",
            r" | |__   _ _ __   __ _ _ __   ___ ___| |__   _   _  __ _| |_| | ___ | |__  ",
            r" |  __| | | '_ \ / _` | '_ \ / __/ _ \ '_ \ | | | |/ _` | __| |/ _ \| '_ \ ",
            r" | |    | | | | | (_| | | | | (_|  __/ | | || |_| | (_| | |_| | (_) | |_) |",
            r" |_|    |_|_| |_|\__,_|_| |_|\___\___|_| |_| \__,_|\__,_|\__|_|\___/|_.__/ ",
            f" Command HUD ativo em {now}",
        ]

        summary_rows = [
            f"Build atual .......... {commit}",
            f"Restarts do Hub ...... {update_count}",
            f"Usuario runtime ...... {os.environ.get('USERNAME', '-')}",
            f"APPDATA .............. {os.environ.get('APPDATA', '-')}",
            f"Endpoint do Hub ...... {hub_url}",
            f"Instancias ativas .... {sum(1 for row in sync_rows if row['enabled'])}/{len(sync_rows)}",
        ]

        check_rows = [
            (
                "Hub updater .......... "
                f"{_format_countdown(updater_state.get('next_check_in_seconds', 0))} "
                f"| proxima: {_format_next_check(updater_state.get('next_check_at', 0))} "
                f"| {updater_state.get('remote', 'origin')}/{updater_state.get('branch', 'main')}"
            ),
            (
                "Updater de instancias  "
                f"{_format_countdown(server_state.get('next_instance_check_in_seconds', 0))} "
                f"| proxima: {_format_next_check(server_state.get('next_instance_check_at', 0))} "
                f"| restarts: {server_state.get('instance_update_restarts', 0)}"
            ),
        ]

        instance_rows = []
        for row in sync_rows:
            status = "ON " if row["enabled"] else "OFF"
            dir_ok = "dir:OK" if row["dir_exists"] else "dir:FALTA"
            main_ok = "main:OK" if row["main_exists"] else "main:FALTA"
            line = (
                f"{status:<3} {row['display_name']:<18} /{str(row['route_prefix']).strip('/'):<10} "
                f"{dir_ok:<9} {main_ok:<10} {row['backend_url']}"
            )
            instance_rows.append(line)
        if not instance_rows:
            instance_rows.append("Nenhuma instancia configurada.")

        event_rows = recent_events if recent_events else ["Aguardando eventos de runtime..."]

        footer_rows = [
            "Hook manual .......... POST /hub/api/update/check (token opcional em HUB_UPDATE_WEBHOOK_SECRET)",
            "Atalhos .............. U = Hub agora | I = instancias agora | A = ambos agora",
            "Ctrl+C ............... encerra o Hub",
            "A tela e fixa: eventos entram aqui sem quebrar a HUD.",
        ]

        screen = "\n\n".join(
            [
                self._box("FINANCEANAHUB COMMAND HUD", header_rows, width),
                self._box("RUNTIME SUMMARY", summary_rows, width),
                self._box("NEXT UPDATE CHECKS", check_rows, width),
                self._box("INSTANCE MAP", instance_rows, width),
                self._box("RECENT EVENTS", event_rows, width),
                self._box("OPERATIONS", footer_rows, width),
            ]
        )
        self._render_screen(screen)


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    settings = AppSettingsStore(base_dir=base_dir)
    config = settings.load()
    sync_rows = _collect_sync_rows(config)
    try:
        update_count = int(os.environ.get("HUB_UPDATE_COUNT", "0"))
    except Exception:
        update_count = 0
    commit = _current_commit(base_dir)
    hud = ConsoleHud()
    hud.add_event(f"[Hub] Processo iniciado com build {commit}")
    hud.add_event(
        "[Hub] Runtime context: "
        f"user={os.environ.get('USERNAME', '-')} "
        f"appdata={os.environ.get('APPDATA', '-')}"
    )

    runtime = InstanceRuntimeManager(instances=config.instances)
    updater = AutoUpdater(
        repo_dir=base_dir,
        enabled=bool(config.auto_update_enabled),
        interval_minutes=int(config.auto_update_interval_minutes),
        remote=str(config.auto_update_remote),
        branch=str(config.auto_update_branch),
        event_callback=hud.add_event,
    )
    server = HubHttpServer(
        host=config.panel_host,
        port=config.panel_port,
        runtime=runtime,
        settings=settings,
        updater=updater,
        console_event_callback=hud.add_event,
    )

    hud.render(
        commit=commit,
        update_count=update_count,
        config=config,
        sync_rows=sync_rows,
        updater_state=updater.get_console_state(),
        server_state=server.get_console_state(),
    )

    updater.start()
    server.start()
    server.start_instance_updater(
        enabled=bool(config.auto_update_enabled),
        interval_minutes=int(config.auto_update_interval_minutes),
    )
    server.warm_up_enabled_backends()
    hud.add_event(f"[Hub] FinanceAnaHub online em http://{config.panel_host}:{config.panel_port}")

    def _handle_console_shortcut(key: str) -> None:
        shortcut = str(key or "").strip().lower()
        if not shortcut:
            return
        if shortcut == "u":
            queued = bool(updater.trigger_check(reason="cmd-hud"))
            hud.add_event(
                "[CMD] Checagem imediata do Hub "
                + ("solicitada pelo atalho U" if queued else "indisponivel no momento")
            )
            return
        if shortcut == "i":
            queued = bool(server.trigger_instance_update_check(reason="cmd-hud"))
            hud.add_event(
                "[CMD] Checagem imediata das instancias "
                + ("solicitada pelo atalho I" if queued else "indisponivel no momento")
            )
            return
        if shortcut == "a":
            hub_ok = bool(updater.trigger_check(reason="cmd-hud"))
            inst_ok = bool(server.trigger_instance_update_check(reason="cmd-hud"))
            if hub_ok or inst_ok:
                hud.add_event(
                    "[CMD] Checagem imediata combinada solicitada pelo atalho A "
                    f"(hub={'ok' if hub_ok else 'off'}, instancias={'ok' if inst_ok else 'off'})"
                )
            else:
                hud.add_event("[CMD] Atalho A ignorado: nenhum updater manual disponivel")
            return

    try:
        while True:
            hud.render(
                commit=commit,
                update_count=update_count,
                config=config,
                sync_rows=sync_rows,
                updater_state=updater.get_console_state(),
                server_state=server.get_console_state(),
            )
            for _ in range(10):
                shortcut = _read_console_shortcut()
                if shortcut:
                    _handle_console_shortcut(shortcut)
                    break
                time.sleep(0.1)
            if updater.consume_restart_request():
                hud.add_event("[Hub Updater] Reiniciando processo do HUB")
                hud.render(
                    commit=commit,
                    update_count=update_count,
                    config=config,
                    sync_rows=sync_rows,
                    updater_state=updater.get_console_state(),
                    server_state=server.get_console_state(),
                )
                runtime.stop_all()
                server.stop()
                updater.stop()
                _restart_process(base_dir)
    except KeyboardInterrupt:
        hud.add_event("[Hub] Encerrando por Ctrl+C")
        hud.render(
            commit=commit,
            update_count=update_count,
            config=config,
            sync_rows=sync_rows,
            updater_state=updater.get_console_state(),
            server_state=server.get_console_state(),
        )
        runtime.stop_all()
        server.stop()
        updater.stop()


if __name__ == "__main__":
    main()
