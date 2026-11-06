# Kullanim: powershell -File test.ps1 -Vt dengeerp_test_a [-Komut pytest|ruff|alembic|build] [pytest argumanlari...]
# Her kodlama paketi KENDI test veritabanini kullanir; ayni anda kosan paketler birbirinin tablolarini bosaltmasin diye.
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Vt = "dengeerp_test_v",
    [string]$Komut = "pytest",
    # Ajan calisma agaci icin kod koku (varsayilan ana kopya). .env her zaman ana kopyadan okunur.
    [string]$Kok = "C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arg
)
$ErrorActionPreference = "Continue"
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
$env:PYTHONUTF8 = '1'
$kok = $Kok
$envSatir = (Get-Content "C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\.env" | Where-Object { $_ -like 'DATABASE_URL=*' }).Substring(13)
$env:TEST_DATABASE_URL = ($envSatir -replace '/dengeerp$', "/$Vt")
Set-Location "$kok\backend"
switch ($Komut) {
    "pytest"  { uv run pytest -q -p no:cacheprovider @Arg }
    "ruff"    { uv run ruff check . ; uv run ruff format --check . }
    "format"  { uv run ruff format . ; uv run ruff check --fix . }
    "alembic" { $env:DATABASE_URL = $env:TEST_DATABASE_URL; uv run alembic @Arg }
    "build"   { Set-Location "$kok\frontend"; npm run build; npx oxlint src }
}
exit $LASTEXITCODE

