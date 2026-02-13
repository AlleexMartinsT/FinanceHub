param(
  [string]$RepoUrl = "https://github.com/AlleexMartinsT/FinanceHub.git",
  [string]$InstallDir = "C:\FinanceHub",
  [string]$Branch = "main",
  [switch]$RunHub
)

$ErrorActionPreference = "Stop"

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
  if (Test-Command "git") {
    return
  }
  Write-Host "[Bootstrap] Git nao encontrado. Tentando instalar via winget..."
  if (-not (Test-Command "winget")) {
    throw "Git ausente e winget indisponivel. Instale Git manualmente."
  }
  & winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
  if (-not (Test-Command "git")) {
    throw "Falha ao instalar Git automaticamente."
  }
}

function Ensure-Python {
  if ((Test-Command "py") -or (Test-Command "python")) {
    return
  }
  Write-Host "[Bootstrap] Python nao encontrado. Tentando instalar via winget..."
  if (-not (Test-Command "winget")) {
    throw "Python ausente e winget indisponivel. Instale Python 3 manualmente."
  }
  & winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
  if (-not ((Test-Command "py") -or (Test-Command "python"))) {
    throw "Falha ao instalar Python automaticamente."
  }
}

function Ensure-GitHub-Access {
  Write-Host "[Bootstrap] Testando acesso ao GitHub..."
  try {
    $null = Invoke-WebRequest -Uri "https://github.com" -Method Head -TimeoutSec 20 -UseBasicParsing
  } catch {
    throw "Sem acesso ao GitHub (https://github.com). Verifique rede/proxy/firewall."
  }
}

Write-Host "[Bootstrap] Verificando pre-requisitos..."
Ensure-Git
Ensure-Python
Ensure-GitHub-Access

if (Test-Path (Join-Path $InstallDir ".git")) {
  Write-Host "[Bootstrap] HUB ja existe. Atualizando..."
  & git -C $InstallDir fetch origin $Branch
  & git -C $InstallDir pull --ff-only origin $Branch
} else {
  Write-Host "[Bootstrap] Clonando HUB em $InstallDir..."
  if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  }
  & git clone --branch $Branch $RepoUrl $InstallDir
}

Set-Location $InstallDir

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "[Bootstrap] Criando ambiente virtual..."
  Invoke-PythonCmd -PyArgs @("-m", "venv", ".venv")
}

Write-Host "[Bootstrap] Atualizando pip..."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip

Write-Host "[Bootstrap] Bootstrap concluido com sucesso."
Write-Host "[Bootstrap] Execute: $InstallDir\run_hub.bat"

if ($RunHub) {
  Write-Host "[Bootstrap] Limpando tela e iniciando HUB..."
  Start-Sleep -Milliseconds 500
  Clear-Host
  & "$InstallDir\run_hub.bat"
}
