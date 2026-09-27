# SB-033 publiceren naar GitHub

Doelrepository: `romanonelstein-blip/superbrain-agent`

De veilige releasebranch is `sb-033-technical-green`. Het script overschrijft `main` niet; het pusht de branch en opent daarna een pull request.

## Windows / PowerShell

1. Pak de ZIP uit.
2. Open de uitgepakte map in Terminal.
3. Zorg dat `git` en `gh` beschikbaar zijn en dat `gh auth status` werkt.
4. Voer uit:

```powershell
powershell -ExecutionPolicy Bypass -File .\publish-to-github.ps1
```

Daarna draait GitHub Actions automatisch de workflow **SB-033 Technical Green**. Die voert een schone `npm ci`, Python regressie/compile, Golden Eval, approval gates, TypeScript tests/typecheck/build, provider-resilience self-test en secret-pattern guard uit.

Live-provider E2E is bewust een aparte releaseproof omdat daarvoor echte providercredentials nodig zijn. Zet nooit API-keys in Git of in de ZIP; gebruik GitHub Actions secrets wanneer die live gate wordt toegevoegd.
