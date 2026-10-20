param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$HttpsPort,

    [ValidateRange(1, 65535)]
    [int]$CertificatePort = 0
)

$ErrorActionPreference = "Stop"

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "La configuración del firewall requiere permisos de administrador."
}

$localPorts = @($HttpsPort)
$displayName = "AmpereStore (red local: $HttpsPort)"
$ruleName = "AmpereStore.Local.$HttpsPort"
$description = "Permite HTTPS de AmpereStore solamente desde la subred local."

if ($CertificatePort -gt 0) {
    $localPorts += $CertificatePort
    $displayName = "AmpereStore (red local: $HttpsPort, $CertificatePort)"
    $ruleName = "AmpereStore.Local.$HttpsPort.$CertificatePort"
    $description = "Permite HTTPS de AmpereStore y la instalación de su certificado solamente desde la subred local."
}

$existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Remove-NetFirewallRule -Name $ruleName
}

New-NetFirewallRule `
    -Name $ruleName `
    -DisplayName $displayName `
    -Description $description `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $localPorts `
    -RemoteAddress LocalSubnet `
    -Profile Any `
    -EdgeTraversalPolicy Block | Out-Null

Write-Host "Firewall configurado para la red local." -ForegroundColor Green
