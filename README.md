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
- The bootstrap console now uses a guided HUD-style output, with environment summary, visible steps, and a final next-actions block.

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

## Home Page Tools

- The `Verificar NFs Faltantes` panel on the Hub home page now uses a responsive layout on smaller screens.
- The Hub home page now uses a more guided server HUD, with a clearer hero section, module map, and more informative maintenance/diagnostic cards.
- In that panel, `Enter` advances to the next visible field, and pressing `Enter` on `Verificar Faltantes` runs the check.
- The `Verificar NFs Faltantes` panel can now select missing NFs and send them straight to Botana `Recuperar e-mails`, so sheet checking and email recovery can happen from the same flow.
- In that same panel, the recovery action now uses the shorter button label `Recuperar NFs`.
- In that same action row, the `Recuperar NFs` button now uses a narrower width so `Selecionar todas as NFs faltantes` stays on a single line more often.
- After sending selected missing NFs to Botana recovery, the Hub now shows a compact loading/progress bar instead of a long status sentence.
- When Botana finishes that recovery, the Hub now distinguishes between `email found`, `already launched`, and `actually added to the sheet`, instead of always showing a generic success message.
- If Botana had to trust attachments/XML because the email subject disagreed with the NF in the attachments, the Hub now opens a warning popup instead of only showing a plain `added to sheet` conclusion.
- The Hub home now includes a `Devlog` tab with front-end events, the latest Hub tail log, and a live snapshot of the current page flow so operational issues can be described with exact steps and outcomes.
- The `Devlog` tab now includes a copy icon overlaid on the snapshot block, in a code-style pattern, to copy the current snapshot, front-end events, and recent Hub events in one step.
- The `Devlog` countdown for the next Hub check now ticks locally every second between server polls instead of jumping several seconds at a time.
- If Botana answers with an authentication error during that recovery flow, the Hub now normalizes the message text and opens a login popup instead of only showing a plain warning.
- That login popup now polls Botana auth state and closes itself automatically once the login is actually confirmed.
- The Botana login popup now opens in a reduced `popup` mode, so it focuses on authentication, hides the extra Hub back button, and closes after successful login instead of redirecting into the full Botana page.
- The Hub desktop layout now uses a slightly wider content container and less compressed summary cards, so helper texts stay on one line more often without stretching the page edge to edge.
- The `Manutenção Guiada` and `Verificar NFs faltantes` cards now use independent heights, so one card no longer stretches the other.
- During `Recuperar NFs`, the Hub now mirrors Botana's real NF count in progress and completion messages, including when only part of the selected NF list was found.
- The `Manutenção Guiada` and `Diagnóstico de Planilha` cards now center their explanatory text, and the `Por Range de NF` inputs move to a dedicated row so the typed numbers stay easier to read.
- In `Diagnóstico de Planilha`, the top two filters now share the same centered column width used by the NF range row, so the whole block stays visually aligned.
- The main action button in `Diagnóstico de Planilha` is now centered on its own row and uses the shorter label `Verificar`.
- The NF range inputs in `Diagnóstico de Planilha` no longer show suggestion placeholders inside the fields.
- In `Diagnóstico de Planilha`, the CSV export action now uses an icon-only button with tooltip instead of the full `Baixar CSV` label.
- In `Diagnóstico de Planilha`, that CSV icon now stays fixed beside `Verificar` and is only enabled when there is data to export.

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

Instant update trigger (webhook-friendly):

```powershell
# Optional secret in the Hub runtime environment:
# set HUB_UPDATE_WEBHOOK_SECRET=your-secret

Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:8877/hub/api/update/check?token=your-secret"
```

Notes:

- Endpoint: `POST /hub/api/update/check`
- If `HUB_UPDATE_WEBHOOK_SECRET` is set, token is required (header `X-Hub-Token` or query `token`).
- Keeps interval-based updater as fallback; this trigger only accelerates checks.

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

Runtime logs on server:

- `C:\FinanceHub\logs\instance_debug.log`
- `C:\FinanceHub\logs\financeiro_principal_stdout.log`
- `C:\FinanceHub\logs\financeiro_principal_stderr.log`
- `C:\FinanceHub\logs\botana_principal_stdout.log`
- `C:\FinanceHub\logs\botana_principal_stderr.log`
- The Hub server CMD now keeps a static ASCII HUD on screen, with runtime summary, instance map, recent events, and countdowns for the next Hub and instance update checks.
- Inside that same CMD HUD, you can trigger instant checks with keyboard shortcuts: `U` for Hub update now, `I` for instance update now, and `A` for both at once.

## Notes

- Keep backend services bound to localhost (`127.0.0.1`) when possible.
- Expose only Hub port externally (for example `8877`) for safer topology.
