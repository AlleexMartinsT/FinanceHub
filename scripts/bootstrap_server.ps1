param(
  [string]$RepoUrl = "https://github.com/AlleexMartinsT/FinanceHub.git",
  [string]$InstallDir = "D:\FinanceAnaHub",
  [string]$Branch = "main",
  [switch]$RunHub
)

$ErrorActionPreference = "Stop"
$script:BootstrapStartedAt = Get-Date

function Write-HudLine {
  param(
    [string]$Text = "",
    [ConsoleColor]$Color = [ConsoleColor]::Gray
  )
  Write-Host $Text -ForegroundColor $Color
}

function Show-BootstrapHeader {
  Clear-Host
  Write-HudLine "============================================================" Cyan
  Write-HudLine "                 FINANCEANAHUB SERVER BOOTSTRAP             " Cyan
  Write-HudLine "============================================================" Cyan
  Write-HudLine ""
  Write-HudLine "Environment" DarkGray
  Write-HudLine ("  Repo       : {0}" -f $RepoUrl) White
  Write-HudLine ("  Branch     : {0}" -f $Branch) White
  Write-HudLine ("  Install dir: {0}" -f $InstallDir) White
  Write-HudLine ("  Run Hub    : {0}" -f ($(if ($RunHub) { "yes" } else { "no" }))) White
  Write-HudLine ""
  Write-HudLine "This bootstrap will check prerequisites, sync the repository," DarkGray
  Write-HudLine "prepare the local runtime, and optionally start the Hub." DarkGray
  Write-HudLine ""
}

function Show-Step {
  param([string]$Title)
  Write-HudLine (">>> " + $Title) Yellow
}

function Show-StepOk {
  param([string]$Text)
  Write-HudLine ("[OK] " + $Text) Green
}

function Show-StepInfo {
  param([string]$Text)
  Write-HudLine ("[INFO] " + $Text) Gray
}

function Show-StepWarn {
  param([string]$Text)
  Write-HudLine ("[WARN] " + $Text) DarkYellow
}

function Show-NextActions {
  $elapsed = [int]((Get-Date) - $script:BootstrapStartedAt).TotalSeconds
  Write-HudLine ""
  Write-HudLine "============================================================" DarkCyan
  Write-HudLine "Bootstrap completed" Green
  Write-HudLine "============================================================" DarkCyan
  Write-HudLine ("  Install dir : {0}" -f $InstallDir) White
  Write-HudLine ("  Duration    : {0}s" -f $elapsed) White
  Write-HudLine ("  Start cmd   : {0}\run_hub.bat" -f $InstallDir) White
  if ($RunHub) {
    Write-HudLine "  Next action : the Hub will start in this console now." White
    Write-HudLine "  Runtime keys: U=Hub update now | I=instance update now | A=both now" White
  } else {
    Write-HudLine "  Next action : run the command above when you want to start the Hub." White
  }
  Write-HudLine ""
}

function Test-Command {
  param([string]$Name)
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonRunner {
  if (Test-Command "py") {
    return @("py", "-3")
  }
  if (Test-Command "python") {
    return @("python")
  }
  throw "Python nao encontrado."
}

function Invoke-PythonCmd {
  param([string[]]$PyArgs)
  $runner = Get-PythonRunner
  $exe = $runner[0]
  $prefix = @()
  if ($runner.Length -gt 1) {
    $prefix = $runner[1..($runner.Length - 1)]
  }
  & $exe @prefix @PyArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Falha ao executar Python: $exe $($prefix + $PyArgs -join ' ')"
  }
}

function Ensure-Git {
  Show-Step "Checking Git"
  if (Test-Command "git") {
    Show-StepOk "Git is available."
    return
  }
  Show-StepWarn "Git not found. Trying to install it with winget."
  if (-not (Test-Command "winget")) {
    throw "Git is missing and winget is unavailable. Install Git manually."
  }
  & winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
  if (-not (Test-Command "git")) {
    throw "Automatic Git installation failed."
  }
  Show-StepOk "Git installed successfully."
}

function Ensure-Python {
  Show-Step "Checking Python"
  if ((Test-Command "py") -or (Test-Command "python")) {
    Show-StepOk "Python is available."
    return
  }
  Show-StepWarn "Python not found. Trying to install it with winget."
  if (-not (Test-Command "winget")) {
    throw "Python is missing and winget is unavailable. Install Python 3 manually."
  }
  & winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
  if (-not ((Test-Command "py") -or (Test-Command "python"))) {
    throw "Automatic Python installation failed."
  }
  Show-StepOk "Python installed successfully."
}

function Ensure-GitHub-Access {
  Show-Step "Checking GitHub access"
  try {
    $null = Invoke-WebRequest -Uri "https://github.com" -Method Head -TimeoutSec 20 -UseBasicParsing
    Show-StepOk "GitHub is reachable."
  } catch {
    throw "Cannot reach GitHub (https://github.com). Check network, proxy, or firewall."
  }
}

Show-BootstrapHeader
Show-StepInfo "Starting prerequisite checks."
Ensure-Git
Ensure-Python
Ensure-GitHub-Access

if (Test-Path (Join-Path $InstallDir ".git")) {
  Show-Step "Syncing repository"
  Show-StepInfo ("Existing Hub detected in {0}. Fetching updates." -f $InstallDir)
  & git -C $InstallDir fetch origin $Branch
  & git -C $InstallDir pull --ff-only origin $Branch
  Show-StepOk "Repository updated."
} else {
  Show-Step "Cloning repository"
  Show-StepInfo ("Cloning Hub into {0}." -f $InstallDir)
  if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  }
  & git clone --branch $Branch $RepoUrl $InstallDir
  Show-StepOk "Repository cloned."
}

Set-Location $InstallDir

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Show-Step "Preparing virtual environment"
  Show-StepInfo "Creating .venv for the Hub runtime."
  Invoke-PythonCmd -PyArgs @("-m", "venv", ".venv")
  Show-StepOk "Virtual environment created."
} else {
  Show-Step "Preparing virtual environment"
  Show-StepOk "Virtual environment already exists."
}

Show-Step "Updating pip"
Show-StepInfo "Refreshing pip inside the Hub virtual environment."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
Show-StepOk "pip updated."

Show-NextActions

if ($RunHub) {
  Show-Step "Starting Hub"
  Show-StepInfo "Cleaning the console and launching the Hub runtime."
  Start-Sleep -Milliseconds 500
  Clear-Host
  & "$InstallDir\run_hub.bat"
}
