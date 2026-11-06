$ErrorActionPreference = "Stop"
$ruleName = "DengeERP Pilot 5050"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5050 -Profile Domain,Private | Out-Null
    Write-Host "Firewall kurali olusturuldu: $ruleName" -ForegroundColor Green
} else {
    Write-Host "Firewall kurali zaten mevcut: $ruleName" -ForegroundColor Yellow
}

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -ExpandProperty IPAddress

Write-Host ""
Write-Host "Diger bilgisayarlardan deneyebileceginiz adresler:" -ForegroundColor Cyan
foreach ($ip in $ips) { Write-Host "  http://$ip`:5050" }
Write-Host ""
Write-Host "Not: Yalnizca sirket LAN/VPN icinde pilot kullanim icindir. SQL Server internete acilmamalidir." -ForegroundColor Yellow
