# FinanceAnaHub

FinanceAnaHub is a gateway/orchestrator for multiple bot instances (for example `FinanceBot` and `AnaBot`) in a single web entry point.

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
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri '<HUB_BOOTSTRAP_PS1_RAW_URL>' -OutFile 'C:\bootstrap_financehub.ps1'; powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\bootstrap_financehub.ps1' -RunHub"
```

What bootstrap does:

- Checks `git`, `python`, and GitHub connectivity.
- Tries auto-install for missing `git/python` using `winget`.
- Clones/updates Hub into `C:\FinanceHub`.
- Creates virtual environment (`.venv`).
- Starts the Hub with `run_hub.bat`.

## Manual Installation (Server)

1. Clone Hub:

```bash
cd C:\
git clone <HUB_REPO_URL> C:\FinanceHub
```

2. Start Hub:

```bash
C:\FinanceHub\run_hub.bat
```

## First-Run Behavior for FinanceBot

By default, `financeiro_principal` uses:

- `app_dir = C:\FinanceBot`
- `backend_url = http://127.0.0.1:8765`
- `auto_clone_missing = true`

If `C:\FinanceBot` does not exist, the Hub can clone it automatically from `repo_url` and then start it.

## Routes

Each instance is served by its own `route_prefix`.

Examples:

- `http://127.0.0.1:8877/financeiro/`
- `http://127.0.0.1:8877/anabot/`

## Configuration File

Settings file:

- `C:\FinanceHub\data\instances.json` (server)

Per-instance fields:

- `instance_id`
- `display_name`
- `instance_type` (`financeiro` or `anabot`)
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

## Notes

- Keep backend services bound to localhost (`127.0.0.1`) when possible.
- Expose only Hub port externally (for example `8877`) for safer topology.
