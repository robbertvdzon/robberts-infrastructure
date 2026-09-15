# AI-toegang en testomgevingen

## Grens tussen begeleid onderzoek en automatische agents

Codex en Claude onderzoeken productie standaard met gerichte alleen-lezen databasequeries en
OpenShift-logs, events en deploymentstatus. Controleer eerst cluster, namespace en database.
Gebruik een read-only account of expliciete read-only transactie. De browser is bedoeld voor
zichtbare gebruikerservaring en rolweergave.

Alleen na expliciete toestemming voor de huidige taak mag begeleid een productiesessie worden
geopend. `tools/copy-agent-access-token.py` kopieert de credential rechtstreeks van de juiste
clustersecret naar het klembord. Plak die in het gemaskeerde agent-loginformulier; geen token in
URL, modelcontext, logs of bestanden. Product Factory behoudt zijn eigen bestaande helper en
`/debug-login`-runbook. Aanmelden autoriseert geen testdata of gegevenswijzigingen in productie.

Agent Runtime accepteert uitsluitend expliciet aan de job toegewezen credentials met een
niet-productiescope (`PROJECT__TEST_*`, `__ACCEPTANCE_*`, `__PREVIEW_*`). De applicatie-logincredentials
eindigen op `_AGENT_TOKEN`. Productie-, cluster-, signing- en beheercredentials horen niet in de
workerconfiguratie. De worker mount uitsluitend de provider-authenticatiebestanden die de CLI nodig
heeft; geen persoonlijk Codex-/Claude-profiel.

## Applicaties

Product Factory, Software Factory, HKH, HKH Autopilot, PVDD, Personal News Feed en Robberts Assistent
gebruiken eigen applicatiesessies met bestaande autorisatie. Nieuwe `/api/auth/agent-session` en
`/api/auth/agent-login`-routes (SF/Assistent onder `/api/v1/auth`) gebruiken `X-AI-Access-Token`.
Elke omgeving heeft een afzonderlijke token, een expliciete identiteitenlijst en toegestane origins.
PR-origins ondersteunen uitsluitend `{pr}` als positief numeriek gedeelte; geen algemene wildcard.
Tokens staan versleuteld in SealedSecrets, niet leesbaar in Git. Productietokens worden niet in de
runtimecatalogus opgenomen. Ingelogde AI-sessies verlopen na een uur.

Product Factory kwaliteitswerk gebruikt acceptatie. Ontbrekende toegang, onbereikbare deployment
of externe integratie blokkeert de test; dat is niet zonder bewijs een productbug. Het bewijs
vermeldt de geteste revision, identiteit, rol en of een echte integratie of fixture is gebruikt.
Een productiecheck blijft publiek en alleen-lezen.

Software Factory kent via `SF_TEST_ACCESS_KEYS` alleen testers een expliciete repositorycredential
toe (`owner/repo=PROJECT__PREVIEW_AGENT_TOKEN`, komma-gescheiden). Deployrechten en clustertokens
worden niet met de tester gedeeld.

## Preview-opruiming

De centrale reconciler draait als `argocd:preview-reconciler`; Software Factory heeft daarnaast
`software-factory:sf-preview-cleanup`. Hun verwijderrechten blijven behouden. Een naam is nooit
voldoende: repository, PR-nummer en ownershiplabels moeten kloppen, GitHub moet closure bevestigen
en de graceperiode plus herhaalde observaties moeten verstreken zijn.

`preview-reconciler/adopt_legacy_previews.py` biedt eerst een dry run. Open previews vereisen een
passende Argo-eigenaar. Gesloten lege previews kunnen worden overgenomen. Achtergebleven workloads
vereisen expliciete beoordeling met `--reviewed-closed`; previews met PVC worden daarmee niet
blind overgenomen. De reconciler voert het verwijderen uit.

`software-factory-test-repository` is bruikbaar als wegwerpbare integratietest voor de factory en
preview-lifecycle. Het is geen gebruikersapplicatie en krijgt geen productielogin. Oude werkruimtes
zoals `product-factory-workspace` krijgen evenmin automatisch credentials omdat ze in de gitmap staan.
