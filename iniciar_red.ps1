param(
    [Parameter(Position = 0)]
    [string]$Ip = "",

    [Parameter(Position = 1)]
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [Parameter(Position = 2)]
    [string]$Domain = ""
)

function Get-ActiveIPv4Address {
    $candidates = @(
        foreach ($networkInterface in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
            if (
                $networkInterface.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up -or
                $networkInterface.NetworkInterfaceType -eq [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback
            ) {
                continue
            }

            $properties = $networkInterface.GetIPProperties()
            $ipv4Gateway = $properties.GatewayAddresses | Where-Object {
                $_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                $_.Address.ToString() -ne "0.0.0.0"
            } | Select-Object -First 1

            if (-not $ipv4Gateway) {
                continue
            }

            foreach ($unicastAddress in $properties.UnicastAddresses) {
                if ($unicastAddress.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
                    continue
                }

                $address = $unicastAddress.Address.ToString()
                if ($address -eq "127.0.0.1" -or $address.StartsWith("169.254.")) {
                    continue
                }

                $isPreferredInterface =
                    $networkInterface.NetworkInterfaceType -eq [System.Net.NetworkInformation.NetworkInterfaceType]::Wireless80211 -or
                    $networkInterface.NetworkInterfaceType -eq [System.Net.NetworkInformation.NetworkInterfaceType]::Ethernet

                [pscustomobject]@{
                    Address       = $address
                    InterfaceName = $networkInterface.Name
                    Priority      = if ($isPreferredInterface) { 0 } else { 1 }
                    Speed         = $networkInterface.Speed
                }
            }
        }
    )

    $candidates |
        Sort-Object Priority, @{ Expression = "Speed"; Descending = $true } |
        Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($Ip)) {
    $detectedNetwork = Get-ActiveIPv4Address
    if (-not $detectedNetwork) {
        throw "No se pudo detectar la IP de la red. Indicála manualmente con -Ip, por ejemplo: .\iniciar_red.ps1 -Ip 192.168.1.25"
    }

    $Ip = $detectedNetwork.Address
    Write-Host "IP detectada automáticamente: $Ip ($($detectedNetwork.InterfaceName))" -ForegroundColor Cyan
}

$parsedAddress = $null
if (
    -not [System.Net.IPAddress]::TryParse($Ip, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork
) {
    throw "Ingresá una dirección IPv4 válida. Ejemplo: .\iniciar_red.ps1 -Ip 192.168.1.25"
}

Set-Location -LiteralPath $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Domain)) {
    $Domain = ($Ip -replace '\.', '-') + ".sslip.io"
}
$Domain = $Domain.Trim().TrimEnd('.').ToLowerInvariant()
if ($Domain -notmatch '^[a-z0-9.-]+$') {
    throw "El dominio HTTPS no es válido."
}

try {
    $resolvedAddresses = [System.Net.Dns]::GetHostAddresses($Domain)
    $domainResolvesToIp = $resolvedAddresses | Where-Object { $_.ToString() -eq $Ip }
    if (-not $domainResolvesToIp) {
        throw "El dominio no resuelve a $Ip."
    }
}
catch {
    throw "No se pudo resolver $Domain hacia $Ip. Revisá la conexión DNS o indicá un dominio propio como tercer parámetro."
}

$certificateDirectory = Join-Path $PSScriptRoot ".certificados"
$caCertificatePath = Join-Path $certificateDirectory "amperestore-ca.cer"
$serverCertificatePath = Join-Path $certificateDirectory "amperestore-server-fullchain.pem"
$serverKeyPath = Join-Path $certificateDirectory "amperestore-server-key.pem"

python -c "import cryptography, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Faltan dependencias. Ejecutá: python -m pip install -r requirements.txt"
}

python scripts/generar_certificado_https.py --ip $Ip --hostname $Domain --output-dir $certificateDirectory
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo generar el certificado HTTPS."
}

$firewallRuleName = "AmpereStore.Local.$Port"
$firewallRuleReady = $false
try {
    $firewallRule = Get-NetFirewallRule -Name $firewallRuleName -ErrorAction Stop
    $firewallRuleReady = $firewallRule.Enabled -eq "True" -and $firewallRule.Action -eq "Allow"
}
catch {
    $firewallRuleReady = $false
}

if (-not $firewallRuleReady) {
    Write-Host ""
    Write-Host "Windows necesita habilitar AmpereStore para los demás equipos de esta red local." -ForegroundColor Yellow
    Write-Host "Se abrirá una confirmación de administrador. La regla quedará limitada a tu subred." -ForegroundColor Yellow
    $firewallScript = Join-Path $PSScriptRoot "scripts\configurar_firewall.ps1"
    $firewallArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$firewallScript`" -HttpsPort $Port"
    try {
        $firewallProcess = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList $firewallArguments `
            -Verb RunAs `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        $firewallRuleReady = $firewallProcess.ExitCode -eq 0
    }
    catch {
        Write-Host "No se configuró el firewall. AmpereStore podría funcionar solamente en esta PC." -ForegroundColor Yellow
    }
}

# Estas variables existen solamente mientras se ejecuta este servidor.
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1,testserver,$Ip,$Domain"
$env:PUBLIC_BASE_URL = "https://${Domain}:$Port"
$env:WEBAUTHN_RP_ID = $Domain
$env:WEBAUTHN_ORIGIN = $env:PUBLIC_BASE_URL

Write-Host ""
Write-Host "AmpereStore disponible en: $env:PUBLIC_BASE_URL" -ForegroundColor Green
Write-Host "No uses la dirección IP directa para Face ID: WebAuthn requiere este dominio." -ForegroundColor Cyan
Write-Host "Los enlaces enviados por email usarán esa misma dirección."
Write-Host ""
Write-Host "En el celular u otra computadora, abrí ese mismo enlace:" -ForegroundColor Cyan
Write-Host $env:PUBLIC_BASE_URL -ForegroundColor Green
Write-Host "No hay que instalar ni descargar ningún certificado."
Write-Host "El navegador va a avisar que el certificado no es de una autoridad conocida:" -ForegroundColor Yellow
Write-Host "elegí Avanzado → Continuar a (o Proceed) para entrar." -ForegroundColor Yellow
Write-Host "Para eliminar ese aviso, dale confianza al certificado generado en:" -ForegroundColor Cyan
Write-Host $caCertificatePath
Write-Host "También se puede descargar desde la tienda en /certificado-local/ (opcional)."
Write-Host "Para detener el servidor presioná Ctrl+C."
Write-Host ""

python scripts/servidor_https.py `
    --host 0.0.0.0 `
    --port $Port `
    --certificate $serverCertificatePath `
    --key $serverKeyPath
