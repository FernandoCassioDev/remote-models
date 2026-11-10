# pc_setup.ps1  -  run on the PC if Ollama runs NATIVELY on Windows.
# Run in an ADMIN PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\pc_setup.ps1                 # default context 65536
#   .\pc_setup.ps1 -Ctx 32768      # smaller context if VRAM is tight
param(
    [int]$Ctx = 65536,
    [string]$KeepAlive = "30m"
)

function Say($m)  { Write-Host "[ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!!] $m" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Warn "Not running as Administrator - the firewall rule will be skipped." }

# 1) Tailscale -------------------------------------------------------------
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Say "Installing Tailscale via winget"
    winget install --id Tailscale.Tailscale -e --accept-package-agreements --accept-source-agreements
    $env:Path += ";C:\Program Files\Tailscale"
}
$tsIp = (& tailscale ip -4 2>$null | Select-Object -First 1)
if (-not $tsIp) {
    Say "Logging into Tailscale (follow the link it prints)"
    & tailscale up
    $tsIp = (& tailscale ip -4 | Select-Object -First 1)
}
Say "Tailscale IP of this machine: $tsIp"

# 2) Ollama environment ----------------------------------------------------
# FLASH_ATTENTION + q8_0 KV cache roughly halve the VRAM used by a long context.
$vars = @{
    OLLAMA_HOST             = "0.0.0.0:11434"
    OLLAMA_CONTEXT_LENGTH   = "$Ctx"
    OLLAMA_KEEP_ALIVE       = $KeepAlive
    OLLAMA_FLASH_ATTENTION  = "1"
    OLLAMA_KV_CACHE_TYPE    = "q8_0"
}
foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], "User")
    Set-Item -Path "Env:$k" -Value $vars[$k]
}
Say "Ollama environment variables set"

# 3) Restart Ollama so it picks them up -----------------------------------
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
if (Test-Path $app) {
    Start-Process $app
    Say "Ollama tray app restarted"
} else {
    Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve"
    Say "ollama serve started in the background"
}

# 4) Firewall: only the Tailscale range may connect -----------------------
if ($isAdmin) {
    if (-not (Get-NetFirewallRule -DisplayName "Ollama (Tailscale only)" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Ollama (Tailscale only)" -Direction Inbound -Protocol TCP `
            -LocalPort 11434 -RemoteAddress "100.64.0.0/10" -Action Allow | Out-Null
    }
    Say "Firewall: port 11434 open to the Tailscale range (100.64.0.0/10) only"
}

# 5) Self-test -------------------------------------------------------------
Start-Sleep -Seconds 4
try {
    Invoke-RestMethod "http://${tsIp}:11434/api/tags" -TimeoutSec 5 | Out-Null
    Say "Ollama answers on http://${tsIp}:11434"
} catch {
    Warn "Ollama didn't answer on ${tsIp}:11434 - give it a few seconds and retry, or check the tray icon."
}

Write-Host ""
Write-Host "Next, on the LAPTOP (Tailscale installed + same account):"
Write-Host "    python3 laptop_setup.py --host $tsIp"
