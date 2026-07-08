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
| `softwarefactory-dashboard` | Ja | Ja — volledig via root-apps (namespace bestond hier al vóór de eerste sync) |
| `agent-access` (read-only ServiceAccount) | Ja | Gedeeltelijk — apply is gescript, token-generatie niet |
| PVC `personal-news-feed/backend-data` | Ja | Ja (StorageClass-provisioned, geen data-backup nodig — check met Robbert of de inhoud vervangbaar is) |
| ~~YouTrack~~ | **Nee — verwijderd 2026-07-08** | n.v.t. |
| ~~29 `pnf-pr-*` preview-namespaces~~ | **Nee — verwijderd 2026-07-08** | n.v.t. (hoorden niet bij open PR's) |

## Details per onderdeel

### 1. ArgoCD
Community `argocd-operator` (OLM Subscription, channel `alpha`) + minimale ArgoCD CR.
Manifests: `manifests/cluster-bootstrap/`. Volledig declaratief, `bootstrap-cluster.sh` stap 1-2.
Kleine kwetsbaarheid: `installPlanApproval: Automatic` zonder gepinde `startingCSV` — operator-versie
kan na reinstall licht afwijken (functioneel geen probleem).

**Namespace-creator-RBAC (2026-07-08, `bootstrap-cluster.sh` stap 3):** de argocd-operator geeft de
`argocd-argocd-application-controller`-ServiceAccount alleen per-namespace `Role`/`RoleBinding`'s (in
namespaces die 'ie al beheert), nooit een cluster-brede `ClusterRoleBinding` — bevestigd met
`oc auth can-i create namespaces --as=system:serviceaccount:argocd:argocd-argocd-application-controller`
(gaf "no" vóór de fix). Nu gefixt met een losse, minimale `ClusterRole` (alleen
`create`/`get`/`list`/`watch`/`update`/`patch` op `namespaces`, bewust **geen** `delete`) —
zie `manifests/cluster-bootstrap/argocd-namespace-creator-rbac.yaml`.

**Deze RBAC-fix lost het "namespaced mode"-probleem NIET volledig op** — met een echte test-PR
(2026-07-08) bleek een tweede, onafhankelijke laag: secret `argocd-default-cluster-config` (namespace
`argocd`) houdt een veld `namespaces` bij — een expliciete, kommagescheiden allow-list van namespaces
die deze ArgoCD-installatie mag beheren. Die lijst vult zichzelf pas ná het zien van een namespace
mét het label `argocd.argoproj.io/managed-by=argocd` (geverifieerd: na handmatig `oc create namespace`
+ `oc label` verscheen de namespace binnen ~10s vanzelf op de allow-list, en synct de Application
daarna probleemloos). **`CreateNamespace=true` kan dus nooit een namespace voor het eerst zelf
aanmaken** — er is altijd een namespace-aanmaak+label-stap buiten ArgoCD nodig (bootstrap.sh,
`namespace.yaml`, of preview-ns-labeller). De namespace-creator-RBAC hierboven blijft wel nuttig
zodra een namespace al bestaat (voor de `update`/`patch` die `managedNamespaceMetadata` gebruikt om
labels te blijven zetten).

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

- **personal-news-feed** — namespace/secrets/preview-ns-labeller/ApplicationSet nog steeds via eigen
  `deploy/bootstrap.sh` (checkt zelf of de cluster-brede bootstrap al gedraaid is). Bevat ook de
  PR-preview-ApplicationSet (zie punt 8 hieronder voor een bekend gat).
- **smb-timemachine** — namespace blijft een losse `oc apply` (cluster-scoped, kan ArgoCD niet), de
  Application zelf komt nu via root-apps.
- **softwarefactory-dashboard** — volledig via root-apps, geen losse stap meer nodig (eigen
  `CreateNamespace=true` werkt al langer probleemloos voor deze specifieke Application).

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

## Wat hierna nog moet (vóór de echte reinstall)

- [ ] Verse `backup-all.sh`-run vlak vóór je de schijf wisselt (sealed-secrets-key + huidige
      cluster-staat als referentie).
- [ ] Overweeg de PR-preview-cleanup-sweep-job (punt 8) te bouwen, of accepteer dat je dit
      af en toe handmatig moet opruimen (`oc get ns | grep pnf-pr-` + cross-check met `gh pr list`).
- [ ] Fysieke schijf-wissel + reinstall volgens [disaster-recovery-playbook.md](disaster-recovery-playbook.md)
      — nu bijgewerkt om zonder YouTrack te werken (3 Applications i.p.v. 4).
