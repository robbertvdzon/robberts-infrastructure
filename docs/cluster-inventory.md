# Cluster-inventarisatie (2026-07-08)

Volledige opname van wat er op dit moment op de OpenShift-cluster staat, per onderdeel: is het
nodig, en komt het bij een reinstall (volgens [disaster-recovery-playbook.md](disaster-recovery-playbook.md))
vanzelf weer correct terug. Gemaakt na het verwijderen van YouTrack en 29 stale
personal-news-feed-preview-namespaces — dit is dus de "schone" staat.

## Samenvatting

| Onderdeel | Nodig? | Reinstall-proof? |
|---|---|---|
| ArgoCD (operator + CR) | Ja | Ja — `bootstrap-cluster.sh` |
| Sealed Secrets controller | Ja | Gedeeltelijk — **grootste risico**, zie hieronder |
| local-path-provisioner + `local-path-storage` namespace | Ja | Ja — `bootstrap-cluster.sh` |
| Reflector | Ja | Ja — `bootstrap-cluster.sh` |
| MachineConfigs (4 custom) | Ja | Ja — `apply-machineconfigs.sh` |
| `personal-news-feed` Application + namespace | Ja | Grotendeels — eigen `deploy/bootstrap.sh` |
| `smb-timemachine` Application + namespace | Ja | Gedeeltelijk — 2 losse `oc apply`-commando's, niet gescript |
| `softwarefactory-dashboard` Application | Ja | Gedeeltelijk — 1 los `oc apply`-commando |
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
- **personal-news-feed** — eigen `deploy/bootstrap.sh`, checkt zelf of de cluster-brede bootstrap
  al gedraaid is. Bevat ook de PR-preview-ApplicationSet (zie punt 8 hieronder voor een bekend gat).
- **smb-timemachine** — namespace + Application worden los ge-`apply`'d (2 commando's, opgeschreven
  in playbook stap 7, niet in een script gegoten).
- **softwarefactory-dashboard** — 1 los `oc apply`-commando (playbook stap 4), leeft in de
  `software-factory`-repo.

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
