# Cluster-inventarisatie (2026-07-08)

Volledige opname van wat er op dit moment op de OpenShift-cluster staat, per onderdeel: is het
nodig, en komt het bij een reinstall (volgens [disaster-recovery-playbook.md](disaster-recovery-playbook.md))
vanzelf weer correct terug. Gemaakt na het verwijderen van YouTrack, 29 stale
personal-news-feed-preview-namespaces, en de app-of-apps-consolidatie (zie
[`manifests/root-app/`](../manifests/root-app/)) — dit is dus de "schone" staat.

## Samenvatting

| Onderdeel | Nodig? | Reinstall-proof? |
|---|---|---|
| ArgoCD (operator + CR) | Ja | Ja — `bootstrap-cluster.sh` |
| Sealed Secrets controller | Ja | Gedeeltelijk — **grootste risico**, zie hieronder |
| local-path-provisioner + `local-path-storage` namespace | Ja | Ja — `bootstrap-cluster.sh` |
| Reflector | Ja | Ja — `bootstrap-cluster.sh` |
| MachineConfigs (4 custom) | Ja | Ja — `apply-machineconfigs.sh` |
| `root-apps` (app-of-apps) | Ja | 1 `oc apply` — beheert de 3 apps hieronder zelf |
| `personal-news-feed` (namespace + secrets + labeller-RBAC) | Ja | Gedeeltelijk — eigen `deploy/bootstrap.sh` blijft verplicht (Application-pointer zelf komt via root-apps, zie hieronder waarom namespace-aanmaak niet vervalt) |
| `smb-timemachine` (namespace) | Ja | Gedeeltelijk — `oc apply -f namespace.yaml` blijft verplicht (zie hieronder) |
| `softwarefactory-dashboard` (namespace) | Ja | Gedeeltelijk — `oc apply -f deploy/base/namespace.yaml` (softwarefactory-repo) blijft verplicht; nooit eerder gescript geweest (gat gevonden 2026-07-08, zie hieronder) |
| `agent-access` (read-only ServiceAccount) | Ja | Gedeeltelijk — apply is gescript, token-generatie niet |
| PVC `personal-news-feed/backend-data` | Ja | Ja (StorageClass-provisioned, geen data-backup nodig — check met Robbert of de inhoud vervangbaar is) |
| `home-assistant` (namespace + hostPath op externe HDD + PVC) | Ja | Grotendeels — zie §10: `/config` op de HDD overleeft een reinstall vanzelf, de recorder-PVC (`local-path`) bewust niet |
| ~~YouTrack~~ | **Nee — verwijderd 2026-07-08** | n.v.t. |
| ~~29 `pnf-pr-*` preview-namespaces~~ | **Nee — verwijderd 2026-07-08** | n.v.t. (hoorden niet bij open PR's) |

## Details per onderdeel

### 1. ArgoCD
Community `argocd-operator` (OLM Subscription, channel `alpha`) + minimale ArgoCD CR.
Manifests: `manifests/cluster-bootstrap/`. Volledig declaratief, `bootstrap-cluster.sh` stap 1-2.
Kleine kwetsbaarheid: `installPlanApproval: Automatic` zonder gepinde `startingCSV` — operator-versie
kan na reinstall licht afwijken (functioneel geen probleem).

**Cluster-scoped instance (sinds 2026-07-08):** de Subscription zet
`ARGOCD_CLUSTER_CONFIG_NAMESPACES=argocd` (operator-env), waardoor de instance cluster-scoped
draait: `CreateNamespace=true` maakt namespaces écht zelf aan en ArgoCD beheert ook cluster-scoped
objecten (Namespaces, ClusterRoles) uit git. Trade-off (controller krijgt praktisch cluster-admin
van de operator) is een bewuste keuze — zie de uitleg in
`manifests/cluster-bootstrap/argocd-operator-subscription.yaml`.

**Historie — het "namespaced mode"-probleem (vóór 2026-07-08):** in namespaced mode gaf de operator
de controller-SA alleen per-namespace `Role`/`RoleBinding`'s. Een losse namespace-creator-`ClusterRole`
(`manifests/cluster-bootstrap/argocd-namespace-creator-rbac.yaml`, nu obsoleet/bewaard als referentie)
gaf raw-RBAC-recht op namespaces, maar loste het probleem aantoonbaar niet op: met een echte test-PR
bleek een tweede, onafhankelijke laag — secret `argocd-default-cluster-config` (namespace `argocd`)
hield een veld `namespaces` bij, een expliciete allow-list die zichzelf pas vulde ná het zien van een
al-bestaande namespace mét het label `argocd.argoproj.io/managed-by=argocd` (na handmatig
`oc create namespace` + `oc label` verscheen de namespace binnen ~10s op de lijst). In die mode kon
`CreateNamespace=true` dus nooit een namespace voor het eerst zelf aanmaken en was er altijd een
stap buiten ArgoCD nodig (bootstrap.sh, `namespace.yaml`, of preview-ns-labeller). Cluster-scoped
mode heft die allow-list op.

### 2. Sealed Secrets — grootste risico in de hele stack
Controller-install zelf is gepind (`v0.27.0`, declaratief). Het probleem is de **private key**: elk
vers cluster genereert een nieuwe, waardoor alle bestaande `SealedSecret`-resources in git
onleesbaar worden. Er zijn nu 3 SealedSecrets in gebruik:
- `personal-news-feed/newsfeed-api-keys`
- `smb-timemachine/samba-timemachine-credentials`
- `software-factory/softwarefactory-dashboard-secrets`

**Moet je onthouden bij de reinstall:** direct na de sealed-secrets-install, vóór je verder gaat:
`./scripts/backup/restore-sealed-secrets-key.sh <backup>/sealed-secrets-keys.yaml`. Zonder dit (of
met een verouderde backup) moet je alle 3 met de hand opnieuw resealen vanuit de plaintext bronnen
(`secrets.env`/`secrets-cluster.env`, alleen lokaal, niet in git). **Draai `backup-all.sh` opnieuw
vlak vóór de reinstall** — de laatste backup is van 2026-07-06/07, en de sealed-secrets-cluster-key
zelf verandert niet vanzelf, maar een verse backup kost niets en geeft zekerheid.

### 3. Storage — local-path-provisioner
`local-path-storage`-namespace: **nodig, niet verwijderen.** Dit ís de enige StorageClass
(`local-path`, default) en backt de echte data van personal-news-feed (`backend-data`-PVC, 5Gi,
Bound). Installatie: rechtstreeks een upstream manifest-URL (`rancher/local-path-provisioner`
`v0.0.30`, gepind), plus SCC-grant en config-patches — alles gescript in `bootstrap-cluster.sh`
stap 5, idempotent.

### 4. Reflector
Secret-mirror naar preview-namespaces, upstream manifest-URL gepind op `v10.0.42`. Gescript,
declaratief, `bootstrap-cluster.sh` stap 6.

### 5. MachineConfigs (4 custom, buiten de cluster-eigen `97-99-*-generated-kubelet`/`99-master-ssh`)
- `51-external-hdd-mount` — externe USB-HDD → `/var/mnt/external-hdd` (Time Machine-bestemming)
- `99-master-disable-ipv6`
- `99-master-hostname`
- `99-master-strip-bad-search-domain`

Alle 4 in git (`manifests/machineconfigs/`), toegepast via `apply-machineconfigs.sh` (idempotent,
`oc apply` per bestand — pakt automatisch alle `.yaml`-bestanden in de map).

### 6. Apps (ArgoCD Applications, 3 stuks — YouTrack was de 4e, nu weg)
Sinds 2026-07-08 via **app-of-apps**: [`manifests/root-app/root-application.yaml`](../manifests/root-app/root-application.yaml)
is de enige Application die je met de hand `apply`'t; die beheert de 3 child-Applications in
[`manifests/root-app/apps/`](../manifests/root-app/apps/) zelf (self-heal + prune aan). De
Application-*pointer* van elke app staat dus op één plek, maar de daadwerkelijke deploy-manifesten
(met CI-gebumpte image-tags) blijven gewoon in de eigen app-repo — geen wijziging aan hoe
personal-news-feed/software-factory zelf deployen.

- **personal-news-feed** — namespace + preview-ns-labeller-RBAC nog steeds via eigen
  `deploy/bootstrap.sh` (checkt zelf of de cluster-brede bootstrap al gedraaid is; nog maar 2
  stappen sinds 2026-07-08, zie `deploy/README.md`). De PR-preview-ApplicationSet, de
  `github-pr-token`-SealedSecret en preview-ns-labeller's Deployment zijn verhuisd naar
  `manifests/root-app/apps/` — puur GitOps, geen losse `oc apply`/afgeleide-secret-stap meer
  (zie punt 8 hieronder voor het bekende, nog niet gefixte namespace-cleanup-gat).
- **smb-timemachine** — namespace blijft een losse `oc apply` (cluster-scoped, kan ArgoCD niet), de
  Application zelf komt nu via root-apps.
- **softwarefactory-dashboard** — de Application zelf via root-apps, maar de namespace **niet**:
  `software-factory`-repo heeft een `deploy/base/namespace.yaml` die bewust buiten
  `kustomization.yaml`'s resources staat (net als bij de andere apps), maar er was nooit een
  bootstrap-script of playbook-stap die 'm daadwerkelijk apply't. Onopgemerkt sinds de namespace
  al bestond (oude, ongedocumenteerde handmatige aanmaak) — gevonden en gefixt in de playbook
  op 2026-07-08 (`oc apply -f deploy/base/namespace.yaml` toegevoegd als expliciete stap).

### 7. agent-access (read-only ServiceAccount voor Claude Code/agents/Telegram-assistent)
`oc apply -k manifests/agent-access/` is volledig declaratief/idempotent. Maar de token +
kubeconfig moeten daarna **met de hand** opnieuw gegenereerd worden (playbook stap 6,
[access-and-credentials.md](access-and-credentials.md)) — geen vast script, een herhaalbare maar
ongescripte procedure ("vraag Claude Code het opnieuw te doen").

### 8. Bekend gat: PR-preview-namespaces ruimen zichzelf niet altijd op
**Root cause gevonden tijdens deze opruiming:** ArgoCD's `ApplicationSet` (pullRequest-generator,
`personal-news-feed-by-claude-code/deploy/applicationset.yaml`) pruned de gegenereerde
**Application** correct zodra een PR sluit/merged, maar de **namespace zelf** (aangemaakt via
`syncOptions: CreateNamespace=true`) wordt door ArgoCD nooit als resource getrackt en dus ook nooit
geprund. Daarnaast heeft de Software Factory's eigen cleanup
(`OcPreviewEnvironmentCleaner`/`monitorPullRequest` in `softwarefactory/orchestrator`) geen retry
en geen onafhankelijke sweep — als de eerste cleanup-poging faalt (transiënte `oc`-fout) of de
story buiten de "top-50 meest-recent-bijgewerkte issues" valt tegen de tijd dat de PR merged,
blijft de namespace voor altijd staan.

Dit veroorzaakte de 29 stale `pnf-pr-*`-namespaces die nu opgeruimd zijn. **Nog niet gefixt** — een
losse periodieke sweep-job (lijst alle `pnf-pr-*`-namespaces op, check per namespace bij GitHub of
de PR nog open is, verwijder zo niet) zou dit structureel oplossen. Aparte taak, niet in deze
opruiming meegenomen.

### 9. Wat er NIET is (bevestigd, geen gat)
Geen cert-manager, geen los monitoring/Prometheus/Grafana, geen eigen ingress-controller (OpenShift
Route/router), geen eigen DNS-server (extern bij one.com). Geen dangling SCC-grants gevonden na het
verwijderen van YouTrack (`anyuid`/`privileged` SCC's bevatten geen youtrack-restjes).

### 10. home-assistant (toegevoegd 2026-07-24)
Manifests volledig in déze repo (geen eigen CI/app-repo), zelfde opzet als smb-timemachine:
Application-pointer via root-apps, namespace via `CreateNamespace=true`. Zie
[`../manifests/home-assistant/README.md`](../manifests/home-assistant/README.md) voor de volledige
afweging. Kort:

- **`/config`** (integraties, `.storage/`, dashboards, automations) staat op een `hostPath` naar de
  externe 16TB-HDD (dezelfde schijf als smb-timemachine, andere submap) — overleeft een reinstall
  automatisch, geen aparte backup-stap nodig. Dit ís het kritieke, niet-zelf-herstellende deel.
- **`home-assistant_v2.db`** (recorder — history/logbook/statistics) staat bewust op een losse PVC
  (`local-path`, 2Gi) — dus NIET reinstall-proof, wordt na reinstall leeg. Bewuste keuze: dit is pure
  tijdreeks-data die vanzelf weer opbouwt, en `local-path` (ext4, journaling) is veiliger voor
  SQLite's zware writes dan de exFAT-HDD.
- LAN-only bereikbaar via een Route (`home-assistant.apps.sno.lab.vdzon.com`, bestaande wildcard-DNS)
  — bewust géén Cloudflare Tunnel, zie de README.
- Nog niet getest op een echte deploy — verifiëren na de eerste sync staat als bekende beperking in
  de README.

## Wat hierna nog moet (vóór de echte reinstall)

- [ ] Verse `backup-all.sh`-run vlak vóór je de schijf wisselt (sealed-secrets-key + huidige
      cluster-staat als referentie).
- [ ] Overweeg de PR-preview-cleanup-sweep-job (punt 8) te bouwen, of accepteer dat je dit
      af en toe handmatig moet opruimen (`oc get ns | grep pnf-pr-` + cross-check met `gh pr list`).
- [ ] Fysieke schijf-wissel + reinstall volgens [disaster-recovery-playbook.md](disaster-recovery-playbook.md)
      — nu bijgewerkt om zonder YouTrack te werken (3 Applications i.p.v. 4).
