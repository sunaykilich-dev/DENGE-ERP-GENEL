# GitHub esitleme (GitLab'a gecise kadar; kullanici istegi 2026-11-06).
#
#   powershell -File araclar\github_esitle.ps1
#
# 1) ERP kodu (denge-erp deposu): her yerel dal -> GitHub erp/<dal>,
#    denge-erp-deneme calisma kopyasinin HEAD'i -> erp/deneme.
#    Gecici ajan dallari (worktree-agent-*) gonderilmez.
#    Commit edilmemis degisiklikler GITMEZ; once commit edin.
# 2) Calisma klasoru deposu (analiz/, araclar/, CLAUDE.md...): degisiklik varsa
#    commit edilir ve main GitHub'a gonderilir. .gitignore'daki kaynak/denge_canli
#    (canli dokum, KVKK) ve .yerel_gizli (parolalar) ASLA gitmez.
#
# Zorla gonderim (--force) YAPMAZ: GitHub'daki dal ilerideyse durur ve soyler.
$ErrorActionPreference = "Stop"
$kok = Split-Path -Parent $PSScriptRoot
$erp = Join-Path $kok "denge-erp"
$deneme = Join-Path $kok "denge-erp-deneme"
$hata = 0

function Gonder($dizin, $uzak, $kaynak, $hedef) {
    git -C $dizin push --quiet $uzak "${kaynak}:refs/heads/$hedef"
    if ($LASTEXITCODE -ne 0) { Write-Host "  X $hedef gonderilemedi" -ForegroundColor Red; $script:hata = 1 }
    else { Write-Host "  + $hedef" -ForegroundColor Green }
}

Write-Host "== ERP kodu -> GitHub erp/*"
$null = git -C $erp remote get-url github
if ($LASTEXITCODE -ne 0) {
    git -C $erp remote add github https://github.com/sunaykilich-dev/DENGE-ERP-GENEL.git
}
$dallar = git -C $erp for-each-ref --format="%(refname:short)" refs/heads
foreach ($d in $dallar) {
    if ($d -like "worktree-agent-*") { continue }
    Gonder $erp github "refs/heads/$d" "erp/$d"
}
if (Test-Path (Join-Path $deneme ".git")) {
    $kirli = git -C $deneme status --porcelain --untracked-files=no
    if ($kirli) { Write-Host "  ! denge-erp-deneme'de commit edilmemis degisiklik var; yalniz son commit gider" -ForegroundColor Yellow }
    Gonder $deneme github "HEAD" "erp/deneme"
}

Write-Host "== Calisma klasoru -> GitHub main"
# Guvenlik: canli dokum ve sir dosyalari takipten cikarilir (silinmez, yalniz
# depodan cikar), sonra eklenen/degisen dosyalarda yeniden denetlenir.
git -C $kok rm -r --cached --quiet --ignore-unmatch kaynak/denge_canli .yerel_gizli
git -C $kok add -A
$yasak = git -C $kok diff --cached --name-only --diff-filter=ACMR | Select-String -Pattern '^kaynak/denge_canli/|^\.yerel_gizli/|(^|/)\.env$|\.sql\.gz$'
if ($yasak) { git -C $kok reset --quiet; Write-Host "  X yasak dosya eklenecekti: $($yasak[0])" -ForegroundColor Red; exit 1 }
git -C $kok diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git -C $kok commit --quiet -m "Esitleme $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    Write-Host "  + commit: $(git -C $kok log -1 --pretty='%h %s')"
} else { Write-Host "  degisiklik yok" }
Gonder $kok origin "HEAD" "main"

if ($hata) { Write-Host "BAZI GONDERIMLER BASARISIZ" -ForegroundColor Red; exit 1 }
Write-Host "ESITLEME TAMAM" -ForegroundColor Green
