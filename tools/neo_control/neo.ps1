# neo.ps1 — Conecta la laptop al WiFi del DJI Neo y corre flight.py con salida EN VIVO
# (para poder teclear VOLAR y usar Ctrl+C=AUTO_LANDING). Restaura tu internet al salir.
#
# Uso:
#   .\neo.ps1                     # DRY seguro (sin despegue)
#   .\neo.ps1 --fly --armed-ok    # VUELO REAL (motores) — lo tecleas tu, viendo el dron
#   .\neo.ps1 osd_reason.py       # correr otro script en vez de flight.py (1er arg = *.py)
#
# REQUISITO: el AP del Neo debe estar ARRIBA. Si no conecta, primero levanta el AP:
#   telefono -> DJI Fly -> conecta al Neo -> apaga el WiFi del telefono -> reintenta.
# El perfil WiFi "DJI-NEO-8499" ya debe existir en Windows (este script NO lleva password).

$ErrorActionPreference = "Continue"
$neoSsid  = "DJI-NEO-8499"
$homeSsid = "depaez_5G"

# 1er argumento puede ser un script .py; si no, se usa flight.py
$rest = @($args)
$script = "flight.py"
if ($rest.Count -gt 0 -and $rest[0] -like "*.py") {
    $script = $rest[0]
    # OJO: $rest[1..($n-1)] con n=1 da el rango DESCENDENTE 1..0 y reinyecta $rest[0].
    if ($rest.Count -gt 1) { $rest = $rest[1..($rest.Count - 1)] } else { $rest = @() }
}
$scriptPath = Join-Path $PSScriptRoot $script

function Get-NeoIP {
    (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like "192.168.2.*" } | Select-Object -First 1).IPAddress
}

# Perfiles de casa a MANUAL para que Windows no salte de vuelta por "sin internet"
netsh wlan show profiles | Select-String "depaez" | ForEach-Object {
    $p = ($_ -split ":")[-1].Trim(); if ($p) { netsh wlan set profileparameter name="$p" connectionmode=manual | Out-Null }
}

try {
    Write-Host "Conectando al Neo ($neoSsid)..." -ForegroundColor Cyan
    $ip = $null
    for ($i = 0; $i -lt 30; $i++) {
        if ($i % 2 -eq 0) { netsh wlan connect name="$neoSsid" ssid="$neoSsid" | Out-Null }
        Start-Sleep -Seconds 1
        $ip = Get-NeoIP
        if ($ip) { break }
    }
    if (-not $ip) {
        Write-Host "No se pudo conectar al Neo. Levanta el AP: telefono -> DJI Fly -> conecta al Neo -> apaga WiFi del telefono, y reintenta." -ForegroundColor Yellow
        return
    }
    Write-Host "Conectado al Neo: $ip" -ForegroundColor Green
    Write-Host "Corriendo: python $script $rest" -ForegroundColor Cyan
    Push-Location $PSScriptRoot
    & python $script @rest      # salida en vivo: VOLAR (input) y Ctrl+C=AUTO_LANDING funcionan
    Pop-Location
}
finally {
    # Restaurar internet de casa SIEMPRE (aunque haya Ctrl+C)
    netsh wlan show profiles | Select-String "depaez" | ForEach-Object {
        $p = ($_ -split ":")[-1].Trim(); if ($p) { netsh wlan set profileparameter name="$p" connectionmode=auto | Out-Null }
    }
    netsh wlan connect name="$homeSsid" ssid="$homeSsid" | Out-Null
    Write-Host "WiFi de casa restaurada." -ForegroundColor Cyan
}
