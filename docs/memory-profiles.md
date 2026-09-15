# Geheugenprofielen voor applicaties en previews

Vanaf 15 september 2026 staan de Java-heap, containerlimiet en memory request in de
applicatierepositories in `deploy/**/**-memory.yaml`. De uitleg per applicatie staat
in `deploy/MEMORY.md`. Productie gebruikt 512 MiB voor PVDD, HKH, HKH Autopilot,
Agent Runtime en Robberts Assistent; Newsfeed, Product Factory en Software Factory
beginnen met 640 MiB. De frontendcontainers gebruiken 32 MiB request / 64 MiB limit.

## Previews op bestaande featurebranches

Een ApplicationSet volgt de SHA van de featurebranch. Een wijziging op `main` van
de applicatie past een bestaande preview dus niet aan. De ApplicationSets in
`manifests/root-app/apps/*-applicationset.yaml` voegen daarom als laatste dezelfde
geheugenprofielen toe. Wijzig bij een ander previewbudget zowel de applicatie-overlay
als deze centrale patches.

| Previewbackend | Request | Containerlimiet | Heap | Collector |
|---|---:|---:|---:|---|
| HKH | 288 MiB | 384 MiB | 128 MiB | Serial |
| HKH Autopilot | 288 MiB | 384 MiB | 128 MiB | Serial |
| Newsfeed | 320 MiB | 448 MiB | 192 MiB | Serial |
| Robberts Assistent | 288 MiB | 384 MiB | 128 MiB | Serial |
| Oude Product Factory dashboard-backend | 320 MiB | 448 MiB | 160 MiB | G1 |
| Oude Product Factory runtime | 320 MiB | 512 MiB | 192 MiB | Serial |

De Newsfeed- en Assistent-previewprofielen zijn startwaarden voor toekomstige
previews; er draaiden daarvan geen previews tijdens deze wijziging.

Gebruik strategic-merge-patches op containernaam en expliciete Deployment-targets.
Dit bewaart andere omgevingsvariabelen en werkt ook wanneer een branchmanifest al
een namespace bevat. Product Factory merge't ook de PR- en CORS-variabelen op naam;
het vervangen van de volledige `env`-lijst zou de JVM-instellingen verwijderen.

## Oude Product Factory-images

Tijdens de rollout bleek dat de registry-tags voor PR #63 niet meer bestaan. De
exacte SHA-getagde images waren nog aanwezig in de CRI-O-cache van de node.
De Product Factory-previewpatches gebruiken daarom `imagePullPolicy: IfNotPresent`.
Dit is passend voor de onveranderlijke SHA-tags en laat dezelfde images opnieuw
starten. Op een lege node of na verwijdering uit de cache zijn deze oude images
nog steeds niet beschikbaar: dan moeten de images opnieuw gepubliceerd worden of
moet de oude preview worden bijgewerkt/opgeruimd.

## Validatie en terugzetten

- Render alle app-omgevingen met Kustomize. Controleer ook de ApplicationSet-patches
  bovenop de daadwerkelijke PR-revisies; alleen YAML-parsing bewijst geen correcte merge.
- Controleer na synchronisatie de rollout, effectieve JVM-opties, werkset,
  health endpoints en eventuele OOM/restarts. Een healthcheck bewijst geen zware belasting.
- Zet een preview terug door de waarden in de ApplicationSet te verhogen of de
  profielcommit te reverten. Alleen het branchmanifest wijzigen is onvoldoende.
- Databases en CPU-budgetten vallen buiten deze geheugenwijziging. Lagere requests
  leveren reserveringsruimte op, maar bewijzen geen besparing van werkelijk RAM.
