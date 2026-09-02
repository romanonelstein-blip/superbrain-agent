# Superbrain Workflow Prompt

**Je bent de open-source engineering-agent van Superbrain Workspace.**

Bouw een veilige, lokale Git/GitHub CLI-workflow volgens deze keten:

**Superbrain → Git/GitHub CLI → lokale repository → Ollama/Codex → tests → preview → auditlog**

## Doel

Maak het mogelijk om vanuit Superbrain lokale softwareprojecten te analyseren, wijzigingen voor te bereiden, tests uit te voeren en een lokale preview te starten. Externe acties moeten transparant en controleerbaar blijven.

## Functionele Eisen

### 1. Repository-detectie
- Detecteer of de geselecteerde map een geldige Git-repository is
- Toon repositorynaam, branch, remote URL en gewijzigde bestanden
- Gebruik alleen lokale Git-commando's voor deze diagnose
- Schrijf niets naar een repository tijdens de diagnose

### 2. GitHub CLI-integratie
- Controleer of GitHub CLI (`gh`) beschikbaar is
- Controleer de loginstatus met `gh auth status`
- Gebruik de bestaande lokale sessie als die aanwezig is
- Vraag nooit om wachtwoorden, 2FA-codes of tokens in de applicatie
- Open eventueel de officiële GitHub-loginflow, maar vul geen credentials automatisch in
- Ondersteun publieke repositories zonder onnodige accountrechten
- Gebruik voor privé-repositories alleen expliciete, lokaal geconfigureerde authenticatie

### 3. Open-source en privacy
- Gebruik open-source tooling waar mogelijk
- Stuur broncode niet naar een externe dienst zonder duidelijke toestemming
- Gebruik Ollama als lokale AI-runtime wanneer die beschikbaar is
- Toon welk model actief is
- Gebruik externe AI alleen als de gebruiker dit expliciet heeft ingeschakeld en de serververbinding veilig is
- Schakel TLS-validatie nooit uit
- Installeer geen onbekende certificaten of software zonder expliciete toestemming

### 4. Ollama/Codex-routering
- Gebruik lokale Ollama voor code-uitleg, samenvatting en planning wanneer beschikbaar
- Gebruik Codex voor codewijzigingen, tests en projectanalyse
- Maak vóór uitvoering een zichtbaar plan
- Toon per stap welke tool wordt gebruikt
- Als Ollama of Codex niet beschikbaar is, toon een concrete foutmelding en een hersteladvies
- Claim nooit dat code is uitgevoerd wanneer alleen een plan is gemaakt

### 5. Veilige wijzigingsworkflow
- Maak eerst een diff of patchvoorstel
- Toon de wijziging aan de gebruiker
- Voer alleen niet-destructieve acties automatisch uit
- Vraag expliciete goedkeuring vóór:
  - push
  - merge
  - publicatie
  - verwijderen
  - wijzigen van accountrechten
  - deployment
  - betaalde diensten
  - externe berichten
- Gebruik bij voorkeur een aparte branch voor voorgestelde wijzigingen
- Bewaar bestaande gebruikerswijzigingen en overschrijf ze niet

### 6. Tests
- Detecteer het projecttype automatisch
- Voer alleen bestaande projecttests uit
- Ondersteun gangbare commando's zoals:
  - npm test
  - npm run check
  - pytest
  - cargo test
  - go test ./...
  - dotnet test
- Toon het volledige resultaat, exitcode en duur
- Stop veilig bij fouten en geef hersteladvies
- Gebruik geen willekeurige installaties of netwerkdownloads zonder toestemming

### 7. Preview
- Start alleen lokale previewservers
- Gebruik een vrije lokale poort
- Toon de preview-URL
- Controleer HTTP-status en basisbeschikbaarheid
- Publiceer niets automatisch naar Vercel, Netlify, GitHub Pages of een andere externe dienst

### 8. Auditlog
Schrijf voor elke actie een append-only lokaal auditrecord met:
- datum en tijd
- repository
- branch
- gebruiker
- gebruikte tool
- uitgevoerde opdracht
- gewijzigde bestanden
- testresultaat
- preview-URL indien aanwezig
- toestemming of blokkade
- resterende risico's

### 9. Foutafhandeling
Gebruik duidelijke statussen:
- voorbereid
- bezig
- geslaagd
- geblokkeerd
- toestemming nodig
- mislukt

Toon nooit alleen een generieke fout zoals "er ging iets mis". Leg uit wat ontbreekt en wat de veiligste volgende stap is.

### 10. Implementatie
- Maak een duidelijke capability registry voor Git, GitHub CLI, Ollama, Codex, tests en preview
- Houd provider-specifieke code achter adapters
- Voeg unit- en integratietests toe
- Voeg documentatie toe met installatie, configuratie, privacy en herstel
- Gebruik geen geheime bypass, geen hardcoded secrets en geen onveilige TLS-opties
- Houd de implementatie lokaal, transparant en open-sourcevriendelijk

## Acceptatiecriteria

- ✅ Een lokale Git-repository kan read-only worden gecontroleerd
- ✅ De GitHub CLI-loginstatus wordt correct getoond
- ✅ Een gebruiker kan een zichtbaar wijzigingsplan laten maken
- ✅ Er wordt een diff getoond vóór wijziging
- ✅ Bestaande tests kunnen veilig worden uitgevoerd
- ✅ Een lokale preview kan worden gestart en gecontroleerd
- ✅ Iedere actie staat in de auditlog
- ✅ Externe of destructieve acties worden geblokkerd totdat de gebruiker ze afzonderlijk goedkeurt
- ✅ De applicatie doet geen onbewezen claims over verbindingen, modellen, tests of deployments

## Implementatie Status

### Phase 1: Core Infrastructure ✅
- [x] GitProvider - Repository detection & diagnostics
- [x] GitHubCliProvider - GitHub CLI status checking
- [x] CapabilityRegistry - Tool detection & versioning
- [x] Type definitions - Complete TypeScript interfaces

### Phase 2: Workflow Management ✅
- [x] AuditLog - Append-only logging system
- [x] ApprovalEngine - Permission & approval workflow
- [x] Basic integration & initialization

### Phase 3: Advanced Features (In Progress)
- [ ] TestRunner - Auto-detect & run project tests
- [ ] PreviewServer - Local preview management
- [ ] OllamaProvider - Local AI integration
- [ ] CodexProvider - External AI fallback
- [ ] DiffGenerator - Patch & change visualization

### Phase 4: Polish & Documentation
- [ ] Integration tests
- [ ] CLI interface
- [ ] Complete documentation
- [ ] Security audit

---

**Repository:** https://github.com/romanonelstein-blip/superbrain-agent

**License:** MIT
