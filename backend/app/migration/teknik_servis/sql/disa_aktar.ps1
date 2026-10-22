<#
  Göç-1 dışa aktarımı (plan §5.3 adım 1) — V1.20.1 test örneğinde, SALT OKUNUR.
  Kullanım (SqlServer modülü kurulu bir Windows makinede):
    powershell -File disa_aktar.ps1 -Sunucu "localhost\SQLTEST" -Veritabani DengeERP -Hedef C:\goc\v1
  Her goc_NN_<Tablo>.sql dosyası <Hedef>\<Tablo>.csv üretir (UTF-8, virgül ayraçlı,
  başlık = kolon adı). CANLI SQL Server'a BAĞLANMAYIN: .bak yedeği ayrı örneğe
  geri yüklenir. Bağlantı Windows kimlik doğrulamasıyla yapılır; parola betiğe yazılmaz.
#>
param(
    [Parameter(Mandatory = $true)][string]$Sunucu,
    [string]$Veritabani = "DengeERP",
    [Parameter(Mandatory = $true)][string]$Hedef
)
$ErrorActionPreference = "Stop"
Import-Module SqlServer
New-Item -ItemType Directory -Force -Path $Hedef | Out-Null
Get-ChildItem -Path $PSScriptRoot -Filter "goc_*.sql" | Sort-Object Name | ForEach-Object {
    $tablo = ($_.BaseName -replace '^goc_\d+_', '')
    $cikti = Join-Path $Hedef "$tablo.csv"
    Write-Host "$($_.Name) -> $cikti"
    Invoke-Sqlcmd -ServerInstance $Sunucu -Database $Veritabani -InputFile $_.FullName `
        -ApplicationIntent ReadOnly -MaxCharLength 1000000 |
        Export-Csv -Path $cikti -NoTypeInformation -Encoding UTF8
}
Write-Host "Tamam. Dizin: $Hedef"