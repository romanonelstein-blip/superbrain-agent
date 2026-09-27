$ErrorActionPreference = "Stop"

$Repo = "romanonelstein-blip/superbrain-agent"
$Branch = "sb-033-technical-green"

Write-Host "=== SuperBrain SB-033 -> GitHub ==="

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is niet gevonden. Installeer Git for Windows."
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is niet gevonden. Installeer GitHub CLI en log in met: gh auth login"
}

Write-Host "1/7 GitHub login controleren..."
gh auth status

Write-Host "2/7 Lokale repository initialiseren/controleren..."
if (-not (Test-Path ".git")) {
    git init
}

$origin = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0 -or -not $origin) {
    git remote add origin "https://github.com/$Repo.git"
} elseif ($origin -notmatch [regex]::Escape($Repo)) {
    throw "Bestaande origin wijst naar '$origin' en niet naar '$Repo'. Stop om de verkeerde repo niet te overschrijven."
}

Write-Host "3/7 Remote ophalen..."
git fetch origin main

Write-Host "4/7 Veilige SB-033 branch maken..."
git checkout -B $Branch origin/main

Write-Host "5/7 SB-033 bestanden committen..."
git add -A
$changes = git status --porcelain
if (-not $changes) {
    Write-Host "Geen wijzigingen om te committen."
} else {
    git commit -m "SB-033: technical-green baseline and CI gate"
}

Write-Host "6/7 Branch pushen..."
git push -u origin $Branch --force-with-lease

Write-Host "7/7 Pull request openen of bestaande tonen..."
$existing = gh pr list --repo $Repo --head $Branch --base main --state open --json url --jq '.[0].url'
if ($existing) {
    Write-Host "Bestaande PR: $existing"
} else {
    gh pr create --repo $Repo --base main --head $Branch `
      --title "SB-033: technical-green baseline" `
      --body "Adds the SB-033 technical-green SuperBrain baseline, clean npm-ci CI verification, Python/TypeScript gates, Golden Eval, resilience self-test, and secret-pattern guard. Live-provider E2E remains a separate credential-gated release proof."
}

Write-Host "KLAAR. Controleer nu de GitHub Actions-run 'SB-033 Technical Green'."
