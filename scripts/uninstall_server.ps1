param(
  [string]$InstallDir = "C:\FinanceHub",
  [string]$FinanceDir = "C:\FinanceBot",
  [string]$BotanaDir = "C:\Botana",
  [switch]$RemoveBackends,
  [switch]$RemoveAppData,
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
    $_.Name -match "python|pythonw|cmd|powershell"
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

if (-not $Force) {
  Write-Host "[Uninstall] Este script remove arquivos do Hub."
  Write-Host "[Uninstall] Use -Force para executar sem confirmacao."
  exit 1
}

Write-Host "[Uninstall] Iniciando desinstalacao..."

$pathsToStop = @($InstallDir)
if ($RemoveBackends) {
  $pathsToStop += @($FinanceDir, $BotanaDir)
}
Stop-ProcessesByPath -Paths $pathsToStop

Remove-PathSafe -Path $InstallDir

if ($RemoveBackends) {
  Remove-PathSafe -Path $FinanceDir
  Remove-PathSafe -Path $BotanaDir
}

if ($RemoveAppData) {
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
