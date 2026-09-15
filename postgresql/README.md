# Centrale PostgreSQL — beheer en herstel

Op 15 september 2026 zijn de elf PostgreSQL-workloads geconsolideerd naar twee
PostgreSQL 16.15-servers op het bestaande single-node OKD-cluster. De migratie is
uitgevoerd met toestemming voor downtime, zonder observatieperiode van 24–48 uur.

## Indeling

| Applicatie | Productie | Acceptatie |
|---|---|---|
| Agent Runtime | `ar_prod` | `ar_acc` |
| HKH | `hkh_prod` | `hkh_acc` |
| HKH Autopilot | `hkh_autopilot_prod` | `hkh_autopilot_acc` |
| Product Factory V2 | `pf_prod` | `pf_acc` |
| Product Factory V1, archief | `pf_legacy_prod`, eigenaar `NOLOGIN` | — |
| PVDD | `pvdd_prod` | `pvdd_acc` |
| Software Factory | `sf_prod`, schema `software_factory` | — |

- Productie: `postgres.postgres-production.svc:5432`, PVC `postgres-data`, 20 GiB.
- Non-production: `postgres.postgres-nonproduction.svc:5432`, PVC 10 GiB.
- Per database een eigen gelijknamige rol, zonder superuser-, creatie-, replicatie-
  of RLS-bypassrechten. Rollen mogen alleen op hun eigen database verbinden.
- TLS `verify-full`, CA uit het applicatie-Secret gemount op `/etc/postgres-ca/ca.crt`.
- Applicaties gebruiken maximaal vijf poolverbindingen; rolgrens tien staat een
  overlappende rollout toe. Servergrenzen: 80 productie, 100 non-production.
- Productie requests/limits: 768/1536 MiB; non-production 384/768 MiB. Shared buffers
  256/128 MiB. Het lokale filesystem geeft geen harde quota op basis van PVC-requests.

Personal News Feed-productie blijft op Neon. PNF-previews gebruiken centrale
non-production. Firestore, SQLite, objectbestanden, Redis en etcd vallen buiten
deze PostgreSQL-migratie.

## Preview-lifecycle

`postgres-preview-controller` draait uitsluitend in `postgres-nonproduction`.
ApplicationSets zetten statische Secret-verwijzingen op de backends. Zolang
`preview-postgres` ontbreekt, start de backend niet met een andere database.

De controller maakt databases als `<app>_pr_<nummer>_<hash-van-namespace-uid>`.
Databases beginnen leeg; Flyway en applicatiefixtures leveren schema en synthetische
testdata. Het wachtwoord is per namespace-UID verschillend. Maximaal acht previews.
Bij een verdwenen namespace verwijdert de controller de geregistreerde database
en rol na een uur grace, met controle van de oorspronkelijke naam en UID.
De bestaande preview-reconciler blijft verantwoordelijk voor de PR-status en het
verwijderen van namespaces. Een heropende PR krijgt een nieuwe database.

Ondersteunde prefixes: `hkh`, `hkh-autopilot`, `product-factory`, `pvdd`, `pnf`.
De bestaande PF-preview 63 is met behoud van zijn gegevens geïmporteerd in
`pf_pr_63_5509532b`. De ApplicationSet ondersteunt de oude runtime/dashboard-structuur
en de huidige backend/frontend-structuur. `preview-images.yml` in Product Factory
bouwt ook oudere PR's met mergeconflicten via een handmatige workflow-dispatch.

PNF-productiesecrets worden niet meer naar previews of ArgoCD gereflecteerd.
De Neon-labeller staat op nul en zijn secretrechten zijn ingetrokken. Het
seal-script kan de oude reflection-annotaties niet opnieuw toevoegen. Nieuwe
PNF- en PF-previews gebruiken uitsluitend acceptatiecredentials voor Agent Runtime.

## Backup

CronJob `postgres-backup` draait dagelijks om **02:15 Europe/Amsterdam**.
Per productiedatabase:

1. Controle van de database-registry, echte exFAT-HDD-mount en vrije ruimte.
2. Custom-format `pg_dump` met een consistente snapshot voor dump, tabelaantallen
   en Flyway-referentiegegevens.
3. `pg_restore --list`, SHA-256 en age-encryptie.
4. Versleutelde metadata, ciphertext-checksums en pas daarna een complete-marker.
5. Retentie: 30 dagelijkse dagen, acht weekpunten en twaalf maandpunten; het
   laatste goede herstelpunt blijft altijd bestaan.

Ook globals worden versleuteld opgeslagen, met `--no-role-passwords`.
Secrets blijven in SealedSecrets; globals bevatten geen herbruikbare wachtwoorden.
De dumpjob ontvangt alleen de publieke age-ontvanger en de leesrol
`platform_backup`. De decryptiesleutel wordt alleen in de hersteljob gemount.

Locatie op de externe HDD:

```text
/var/mnt/external-hdd/postgres-backups/central/
  <database>/<UTC-run>/
    <database>.dump.age
    <database>.dump.age.sha256
    metadata.json.age
    metadata.json.age.sha256
    complete.json
  globals/<UTC-run>.sql.age
  status.json
  restore-status.json
```

De oude backup-CronJobs zijn gesuspendeerd na de bewezen centrale dekking.
Non-production is herbouwbaar en heeft geen dagelijkse databackup; de bestaande
acceptatie- en PR-63-bronnen zijn tijdens deze migratie wel geback-upt en behouden.

## Automatische proefrestore

CronJob `postgres-restorecheck` draait zondag om **03:30 Europe/Amsterdam**.
Hij decrypt en controleert de laatste complete backup van iedere productiedatabase,
herstelt die in een tijdelijke `restorecheck_*`-database op dezelfde server, en
controleert aantallen, Flyway-checksums/status, indexgeldigheid en toegangsisolatie.
De tijdelijke database en rol worden daarna verwijderd. Deze technische job bevat
geen AI-agent en start geen applicatie tegen de productiedata. Er is geen derde
permanente PostgreSQL-server.

Handmatig uitvoeren, met telkens een unieke jobnaam:

```sh
oc create job postgres-backup-manual-YYYYMMDDHHMM --from=cronjob/postgres-backup -n postgres-production
oc create job postgres-restore-manual-YYYYMMDDHHMM --from=cronjob/postgres-restorecheck -n postgres-production
oc get jobs -n postgres-production
oc logs job/NAAM -n postgres-production
```

Joblogs bevatten technische status en databasenamen, geen rijen, SQL-statements
of credentials. Doe geen parallelle handmatige restorechecks of provisioning tijdens
een hersteloperatie. De geplande jobs gebruiken `concurrencyPolicy: Forbid`.

## Sleutels en volledig herstel

De oorspronkelijke private migratiebestanden en age-identiteit staan op Robberts
Mac onder `~/.local/share/postgresql-consolidation/20260915/` (map 0700, bestanden
0600). De identiteit staat bovendien versleuteld als SealedSecret
`postgres-backup-encryption`. Behoud ook de bestaande SealedSecrets-controllersleutels.
De private age-identiteit staat niet in Git en niet als plaintext op de backup-HDD.

Bij verlies van de databaseserver:

1. Stop de betrokken writers. Bewaar de nog aanwezige gegevens en foutdiagnostiek.
2. Herstel de PostgreSQL-manifests en SealedSecrets. Bij een nieuw cluster moet
   eerst de SealedSecrets-controllersleutel of de afzonderlijk bewaarde secrets
   worden hersteld. Normale Argo-sync heeft de lokale generator-state niet nodig.
3. Provision de rollen/databases uit de registry. Kopieer een **complete** backup
   en metadata naar een besloten herstelomgeving en verifieer ciphertext-SHA-256.
4. Decrypt met age, verifieer de plaintext-checksum uit de metadata en voer
   `pg_restore --list` uit. Herstel naar een lege database met de eigen rol,
   `--no-owner --no-acl --exit-on-error --single-transaction`.
5. Controleer schema, Flyway, tabel- en sequencegegevens, indexen en rechten.
   Zet geen volledige oude globals blind terug over bestaande rollen.
6. Start de applicatie met haar eigen Secret, verifieer health en relevante
   functionele leesacties, en geef daarna writes vrij.

Dagelijkse dumps betekenen maximaal ongeveer één dag verlies sinds het laatste
goede herstelpunt. Er is geen HA of point-in-time recovery; beide servers draaien
op dezelfde node. Dit is de gekozen eenvoudige opzet voor één gebruiker.

## Oude bronnen en terugschakelen

Alle elf oude databaseworkloads staan op nul. Hun PVC's/PV's en laatste migratiedumps
zijn bewaard. De database-PV's hebben `Retain`; PVC's zijn tegen Argo-prune/delete
beschermd. Ze worden niet automatisch verwijderd. De reeds losgekoppelde PF-V1-
Deployment blijft als beschermde oude bron aanwezig, buiten de huidige V2-overlay.

**Na de migratie zijn er nieuwe writes op centraal. Alleen de oude pod opnieuw
starten is dan geen volledige rollback.** Stop writers, maak een actuele dump van
centraal en herstel die naar een lege rollbackdatabase. Controleer compatibiliteit
en gegevens voordat de applicatie wordt teruggeschakeld. De oude schijf is een
historisch herstelpunt, geen actuele replica.

## GitOps en wijzigingen

Argo Applications `postgres-production` en `postgres-nonproduction` gebruiken
AppProject `postgresql-platform`, met alleen deze namespaces en deze Git-repository.
Volgorde: server/credentials, provisioning-hook (wave 1), operationele deployments
(wave 2). De StatefulSet gebruikt `OnDelete`: een wijziging van de PostgreSQL-image
of startupconfiguratie vraagt een gecontroleerde podherstart; Argo wijzigt niet
onverwacht een draaiende databaseserver.

`bootstrap.py` en `complete_manifests.py` zijn operatorgereedschap voor het genereren
van manifests. Ze vereisen de oorspronkelijke private state en weigeren die stil te
vervangen. Gebruik ze niet als AI-workerjob. `migrate.py` en
`migrate_existing_preview.py` documenteren de eenmalige migratie; voer ze niet
opnieuw uit op gevulde doelen.

## Monitoring

De bestaande cluster-Prometheus verzamelt de exporters via ServiceMonitors en
afzonderlijke discovery-leesrechten in de twee namespaces. Er draait geen extra
Prometheus-stack. Metrics bevatten onder meer databasegrootte, verbindingen per
rol/database, locks, deadlocks, tempbytes, WAL-grootte, transaction-ID-leeftijd,
langste transactie, backup-/restorestatus en duur, HDD-capaciteit en preview-orphans.
Geheugen, CPU, OOM/restarts en filesystemstatistieken komen uit de bestaande
clustercollectors. Er worden geen SQL-teksten of queryparameters geëxporteerd.

PrometheusRules alarmeren op uitval, ontbrekende metrics, mislukte of te oude
backups/restores, hoge verbindingen/geheugen, OOM, volle opslag, lange transacties,
locks, vacuumleeftijd, WAL-groei en vastgelopen previewprovisioning/opruiming.
Meldingen staan in OpenShift **Observe → Alerting**. Het cluster had geen extern
Alertmanager-notificatiekanaal; er is geen e-mail- of chatbestemming verzonnen.

## Uitgevoerde verificatie

- Logische restores van alle elf brondatabases, met dezelfde aantallen, Flyway-
  checksums en sequencewaarden vóór vrijgave van writers.
- Nieuwe PostgreSQL-schema's voor beide voormalige H2-acceptatieomgevingen.
- Gezonde deployments na iedere migratie en opnieuw na een herstart van beide
  centrale servers; alle 13 applicatiedatabases bleven behouden.
- Volledige encrypted backup en echte restorecontrole van alle zeven productiedatabases.
- Nieuwe PNF- en huidige PF-previews vanaf lege databases; daarna verwijdering van
  namespace, database en rol via de normale controllerlogica met een reeds verlopen
  grace-timestamp, uitsluitend voor de twee synthetische testpreviews.
- Echte TLS-verbinding vanuit een preview; verkeerde database, onversleutelde
  verbinding en verkeerde TLS-hostnaam geweigerd. Productie-netwerktoegang geblokkeerd.
- Geen cross-app CONNECT-grants of verhoogde applicatierollen; admission-policy
  weigert controllerwrites buiten de previewnamespaces en naar andere Secret-namen.
- Applicatieguard-tests en repository-CI voor HKH/HKH Autopilot; gerichte guard-tests
  en gepubliceerde images voor PF-63; rendercontrole van alle gewijzigde overlays.

De historische V8/V9-migraties van HKH Autopilot zijn uit Git teruggehaald met
checksums die exact overeenkomen met de reeds toegepaste productiemigraties.

Bestaande Secrets zijn tijdens de overdracht aan SealedSecrets expliciet geadopteerd
met `sealedsecrets.bitnami.com/managed=true`, volgens de
[SealedSecrets-documentatie](https://github.com/bitnami/sealed-secrets#managing-existing-secrets).
