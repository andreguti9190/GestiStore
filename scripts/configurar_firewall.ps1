param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$HttpsPort,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$CertificatePort
)

$ErrorActionPreference = "Stop"

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "La configuración del firewall requiere permisos de administrador."
}

$ruleName = "AmpereStore.Local.$HttpsPort.$CertificatePort"
$existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Remove-NetFirewallRule -Name $ruleName
}

New-NetFirewallRule `
    -Name $ruleName `
    -DisplayName "AmpereStore (red local: $HttpsPort, $CertificatePort)" `
    -Description "Permite HTTPS de AmpereStore y la instalación de su certificado solamente desde la subred local." `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $HttpsPort, $CertificatePort `
    -RemoteAddress LocalSubnet `
    -Profile Any `
    -EdgeTraversalPolicy Block | Out-Null

Write-Host "Firewall configurado para la red local." -ForegroundColor Green
