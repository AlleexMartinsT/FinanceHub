# FinanceHub

FinanceHub is a gateway/orchestrator for multiple bot instances (for example `FinanceBot` and `Botana`) in a single web entry point.

## What This Project Does

- Provides one central web access point.
- Proxies each configured instance by route prefix.
- Auto-starts enabled backends.
- Can auto-clone missing backend repositories on first run.
- Supports Git-based auto-update for the Hub itself.

## Folder Structure

- `src/main.py`: Hub bootstrap and lifecycle.
- `src/web/`: HTTP gateway/proxy server.
- `src/instances/`: instance models.
- `src/storage/`: settings persistence (`instances.json`).
- `scripts/bootstrap_server.ps1`: first-install bootstrap script.
- `run_hub.bat`: production start script.
- `update_hub.bat`: manual Git update helper.

## Quick Start (Local)

```bash
cd <LOCAL_REPO_PATH>
python src/main.py
```

Default Hub URL:

- `http://127.0.0.1:8877`

## Clean First Installation (Server, Recommended)

Use PowerShell as Administrator:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/AlleexMartinsT/FinanceHub/main/scripts/bootstrap_server.ps1' -OutFile 'C:\bootstrap_financehub.ps1'; powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\bootstrap_financehub.ps1' -RunHub"
```

Note:

- For this repository, the bootstrap URL above is the same for all users.
- Use placeholders only if you are creating documentation for a reusable template or for another repository.

What bootstrap does:

- Checks `git`, `python`, and GitHub connectivity.
- Tries auto-install for missing `git/python` using `winget`.
- Clones/updates Hub into `C:\FinanceHub`.
- Creates virtual environment (`.venv`).
- Starts the Hub with `run_hub.bat`.

At first backend startup, the Hub can also:

- create backend `.venv` if missing
- install backend dependencies from `requirements.txt`
- auto-clone missing backend repository when `auto_clone_missing = true`

### Botana First-Run Notes (Important)

When `botana_principal` is enabled, the Hub will try to clone/start `C:\Botana` automatically.

Requirements:

- `C:\FinanceHub\data\instances.json` must have:
  - `instance_type = "botana"`
  - `enabled = true`
  - `app_dir = "C:\\Botana"`
  - `repo_url = "https://github.com/AlleexMartinsT/Botana.git"`
  - `auto_clone_missing = true`
  - `start_args = ["main.py","--server","--host","127.0.0.1","--port","8865"]`

If dependency installation fails in Botana, run manually on server:

```powershell
cd C:\Botana
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Manual Installation (Server)

1. Clone Hub:

```bash
cd C:\
git clone https://github.com/AlleexMartinsT/FinanceHub.git C:\FinanceHub
```

2. Start Hub:

```bash
C:\FinanceHub\run_hub.bat
```

## First-Run Behavior for Backends

By default, `financeiro_principal` uses:

- `app_dir = C:\FinanceBot`
- `backend_url = http://127.0.0.1:8765`
- `auto_clone_missing = true`

If `C:\FinanceBot` does not exist, the Hub can clone it automatically from `repo_url` and then start it.

By default, `botana_principal` uses:

- `app_dir = C:\Botana`
- `backend_url = http://127.0.0.1:8865`
- `auto_clone_missing = true`

If `C:\Botana` does not exist, the Hub can clone it automatically from `repo_url` and then start it.

## Routes

Each instance is served by its own `route_prefix`.

Examples:

- `http://127.0.0.1:8877/financeiro/`
- `http://127.0.0.1:8877/botana/`

## Configuration File

Settings file:

- `C:\FinanceHub\data\instances.json` (server)

Per-instance fields:

- `instance_id`
- `display_name`
- `instance_type` (`financeiro` or `botana`)
- `enabled`
- `interval_seconds`
- `backend_url`
- `app_dir`
- `start_args`
- `route_prefix`
- `repo_url`
- `repo_branch`
- `auto_clone_missing`
- `credentials_key`
- `notes`

## Hub Auto-Update (Git)

Hub supports automatic Git updates with process restart.

Global settings in `instances.json`:

- `auto_update_enabled`
- `auto_update_interval_minutes`
- `auto_update_remote`
- `auto_update_branch`

Requirements:

- Hub must run from a valid Git clone (`.git` folder present).
- `git` must be available in PATH for the runtime user.

## Operations

Start:

```bash
C:\FinanceHub\run_hub.bat
```

Manual update:

```bash
C:\FinanceHub\update_hub.bat
```

Uninstall (Hub only):

```bash
C:\FinanceHub\uninstall_hub.bat
```

By default, `uninstall_hub.bat` now opens a small menu:

- `1` Complete uninstall (Hub + FinanceBot + Botana + AppData)
- `2` Custom uninstall (choose each component)
- `3` Hub only
- `0` Cancel

Uninstall Hub + backends + AppData:

```bash
C:\FinanceHub\uninstall_hub.bat -RemoveBackends -RemoveAppData
```

Equivalent PowerShell command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\FinanceHub\scripts\uninstall_server.ps1 -Force -RemoveBackends -RemoveAppData
```

Non-interactive examples:

```powershell
# Hub + both backends + AppData (no confirmation)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\FinanceHub\scripts\uninstall_server.ps1 -Force -RemoveBackends -RemoveAppData

# Remove only Botana
powershell -NoProfile -ExecutionPolicy Bypass -File C:\FinanceHub\scripts\uninstall_server.ps1 -Force -RemoveBotana
```

## Login/Sync Diagnostics

If Botana shows "Falha ao conectar com o servidor" during login, verify runtime context in Hub startup logs.

Expected line:

- `[Hub] Runtime context: user=<USER> appdata=<PATH>`

Botana reads auth file from:

- `%APPDATA%\Botana\panel_auth.json` of the same runtime user shown above.

If Hub runs as a different Windows user (or `SYSTEM`), it may use a different `%APPDATA%` and different credentials file.

## Notes

- Keep backend services bound to localhost (`127.0.0.1`) when possible.
- Expose only Hub port externally (for example `8877`) for safer topology.
