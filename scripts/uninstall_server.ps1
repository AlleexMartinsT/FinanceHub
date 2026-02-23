param(
  [string]$InstallDir = "C:\FinanceHub",
  [string]$FinanceDir = "C:\FinanceBot",
  [string]$BotanaDir = "C:\Botana",
  [switch]$RemoveBackends,
  [switch]$RemoveFinance,
  [switch]$RemoveBotana,
  [switch]$RemoveAppData,
  [switch]$NoMenu,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Stop-ProcessesByPath {
  param([string[]]$Paths)
  $normalized = @()
  foreach ($p in $Paths) {
    if ([string]::IsNullOrWhiteSpace($p)) { continue }
    try {
      $normalized += [System.IO.Path]::GetFullPath($p).ToLowerInvariant()
    } catch {
      $normalized += $p.ToLowerInvariant()
    }
  }

  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "python|pythonw"
  }

  foreach ($proc in $procs) {
    $cmd = [string]$proc.CommandLine
    if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
    $cmdLower = $cmd.ToLowerInvariant()
    $match = $false
    foreach ($p in $normalized) {
      if ($cmdLower.Contains($p)) {
        $match = $true
        break
      }
    }
    if (-not $match) { continue }
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host "[Uninstall] Processo finalizado PID=$($proc.ProcessId)"
    } catch {}
  }
}

function Remove-PathSafe {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return }
  if (-not (Test-Path $Path)) {
    Write-Host "[Uninstall] Nao encontrado: $Path"
    return
  }
  try {
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    Write-Host "[Uninstall] Removido: $Path"
  } catch {
    Write-Warning "[Uninstall] Falha ao remover $Path : $($_.Exception.Message)"
  }
}

function Ask-YesNo {
  param(
    [string]$Question,
    [bool]$Default = $true
  )
  $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
  $ans = Read-Host "$Question $suffix"
  if ([string]::IsNullOrWhiteSpace($ans)) { return $Default }
  $val = $ans.Trim().ToLowerInvariant()
  return @("y","yes","s","sim") -contains $val
}

function Resolve-UninstallSelection {
  $selection = [ordered]@{
    RemoveHub = $true
    RemoveFinance = $false
    RemoveBotana = $false
    RemoveAppData = $false
  }

  if ($RemoveBackends) {
    $selection.RemoveFinance = $true
    $selection.RemoveBotana = $true
  }
  if ($RemoveFinance) { $selection.RemoveFinance = $true }
  if ($RemoveBotana) { $selection.RemoveBotana = $true }
  if ($RemoveAppData) { $selection.RemoveAppData = $true }

  $hasExplicit =
    $PSBoundParameters.ContainsKey("RemoveBackends") -or
    $PSBoundParameters.ContainsKey("RemoveFinance") -or
    $PSBoundParameters.ContainsKey("RemoveBotana") -or
    $PSBoundParameters.ContainsKey("RemoveAppData")

  if (-not $NoMenu -and -not $hasExplicit) {
    Write-Host ""
    Write-Host "=== Desinstalador FinanceHub ==="
    Write-Host "1) Completa (Hub + FinanceBot + Botana + AppData)"
    Write-Host "2) Personalizada"
    Write-Host "3) Apenas Hub"
    Write-Host "0) Cancelar"
    $opt = Read-Host "Escolha uma opcao"
    switch ($opt) {
      "1" {
        $selection.RemoveHub = $true
        $selection.RemoveFinance = $true
        $selection.RemoveBotana = $true
        $selection.RemoveAppData = $true
      }
      "2" {
        $selection.RemoveHub = Ask-YesNo "Remover HUB ($InstallDir)?" $true
        $selection.RemoveFinance = Ask-YesNo "Remover FinanceBot ($FinanceDir)?" $false
        $selection.RemoveBotana = Ask-YesNo "Remover Botana ($BotanaDir)?" $false
        $selection.RemoveAppData = Ask-YesNo "Remover AppData (configuracoes/credenciais locais)?" $false
      }
      "3" {
        $selection.RemoveHub = $true
      }
      default {
        Write-Host "[Uninstall] Cancelado pelo usuario."
        exit 0
      }
    }
  }

  return $selection
}

$plan = Resolve-UninstallSelection

Write-Host "[Uninstall] Plano selecionado:"
Write-Host ("  - Hub:      {0}" -f ($(if ($plan.RemoveHub) { "SIM" } else { "NAO" })))
Write-Host ("  - Finance:  {0}" -f ($(if ($plan.RemoveFinance) { "SIM" } else { "NAO" })))
Write-Host ("  - Botana:   {0}" -f ($(if ($plan.RemoveBotana) { "SIM" } else { "NAO" })))
Write-Host ("  - AppData:  {0}" -f ($(if ($plan.RemoveAppData) { "SIM" } else { "NAO" })))

if (-not $Force) {
  if (-not (Ask-YesNo "Confirmar desinstalacao?" $true)) {
    Write-Host "[Uninstall] Operacao cancelada."
    exit 0
  }
}

Write-Host "[Uninstall] Iniciando desinstalacao..."
try { Set-Location "C:\" } catch {}

$pathsToStop = @()
if ($plan.RemoveHub) { $pathsToStop += @($InstallDir) }
if ($plan.RemoveFinance) { $pathsToStop += @($FinanceDir) }
if ($plan.RemoveBotana) { $pathsToStop += @($BotanaDir) }
Stop-ProcessesByPath -Paths $pathsToStop

if ($plan.RemoveHub) {
  Remove-PathSafe -Path $InstallDir
}

if ($plan.RemoveFinance) {
  Remove-PathSafe -Path $FinanceDir
}
if ($plan.RemoveBotana) {
  Remove-PathSafe -Path $BotanaDir
}

if ($plan.RemoveAppData) {
  $candidates = @(
    (Join-Path $env:APPDATA "FinanceBot"),
    (Join-Path $env:APPDATA "Botana"),
    (Join-Path $env:APPDATA "FinanceHub"),
    "C:\Users\Administrator\AppData\Roaming\FinanceBot",
    "C:\Users\Administrator\AppData\Roaming\Botana",
    "C:\Users\Administrator\AppData\Roaming\FinanceHub",
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\FinanceBot",
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\Botana",
    "C:\Windows\System32\config\systemprofile\AppData\Roaming\FinanceHub"
  )
  $unique = $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
  foreach ($p in $unique) { Remove-PathSafe -Path $p }
}

Write-Host "[Uninstall] Concluido."
Write-Host "[Uninstall] Se necessario, execute bootstrap novamente para instalar do zero."
exit 0
