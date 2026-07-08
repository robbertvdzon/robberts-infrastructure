# Architectuur

## Hardware

- ASUS PRIME H410M-K, Intel/AMD64
- 32GB RAM
- `/dev/sda` — 240GB SATA SSD, OS-schijf (RHCOS/SCOS)
- Externe USB-HDD ("Verbatim Desktop HDD 3.0", 3.7TB, exFAT), gemount op
  `/var/mnt/external-hdd` — de Time Machine-bestemming (zie
  [../manifests/smb-timemachine/README.md](../manifests/smb-timemachine/README.md)). Sinds
  2026-07-08 de definitieve opzet; vervangt de interne 4TB-schijf (`/dev/sdb`, was gemount op
  `/var/mnt/localpv`) — die schijf is niet meer nodig en de MachineConfig ervoor
  (`50-local-storage-mount`) is verwijderd. Bewuste keuze voor extern/exFAT: bij een kapotte
  OpenShift-machine kan de schijf losgekoppeld en direct op een Mac aangesloten worden.
- 1Gbps bedraad ethernet, vast IP `192.168.178.64` via DHCP-reservation op de Ziggo router (MAC `24:4B:FE:82:0D:4D`)

## Cluster

- OKD single-node (SNO), SCOS-variant, versie `4.21.0-okd-scos.10`
- Cluster-naam `sno`, base domain `lab.vdzon.com`
- OVN-Kubernetes, IPv4-only (IPv6 bewust uitgezet — zie install-quirks hieronder)
- Enige StorageClass: `local-path` (rancher.io/local-path), path `/var/lib/local-path-provisioner`
  op de **kleine SSD** — geen enkele schijf (extern of voormalig intern) wordt door
  Kubernetes-storage gebruikt; de externe HDD is puur een hostPath-mount voor de SMB-share.

## Netwerklaag / toegang van buiten

Geen port-forwarding op de router. Elke app die van buiten bereikbaar moet zijn draait een
eigen `cloudflared`-pod (Cloudflare Tunnel, uitgaande verbinding) met een public hostname op
`vdzonsoftware.nl`. DNS voor dat domein loopt via one.com.

**One.com DNS-gotcha (zie [manual-external-steps.md](manual-external-steps.md)):** er staat een
wildcard `A *.vdzon.com` naar one.com-hosting. Met `ndots:5` in pod-`resolv.conf` en een
geërfd `search lab.vdzon.com` (van Ziggo-DHCP) matcht dit wildcard *cluster-interne* servicenamen
die niet bestaan, en levert een fout IP terug in plaats van NXDOMAIN. Opgelost via de
`99-master-strip-bad-search-domain` MachineConfig (zie hieronder) — **niet DNS-side gefixt**,
dus deze MachineConfig moet na elke reinstall terugkomen.

## Node-level configuratie (MachineConfigs)

Deze zaten alleen live op het cluster of in `~/okd-sno/`, nu overgezet naar
[`manifests/machineconfigs/`](../manifests/machineconfigs):

1. **`51-external-hdd-mount`** — mount de externe USB-HDD op `/var/mnt/external-hdd` (exFAT,
   `/dev/disk/by-id/usb-Verbatim...`). Vervangt `50-local-storage-mount` (verwijderd 2026-07-08 —
   zie hardware hierboven).
2. **`99-master-strip-bad-search-domain`** — NetworkManager dispatcher-script dat
   `lab.vdzon.com` uit de DNS search-line van elke pod strip't (zie DNS-gotcha hierboven).
   Zonder deze fix: console 60s+ per pagina, exact het probleem uit de originele install.

## Toegang / credentials

Twee niveaus: een break-glass admin-credential (1Password, alleen handmatig,
alleen voor install en ArgoCD-bootstrap) en een read-only `claude-agent`
ServiceAccount (met één bewuste, gedocumenteerde schrijf-uitzondering voor
preview-namespace-cleanup) voor al het automatische gebruik — Claude Code,
tester/refiner-agents, de Telegram-assistent. Volledige uitleg en de exacte
RBAC-verificatie: [access-and-credentials.md](access-and-credentials.md).

## GitOps-laag

- **ArgoCD** (community `argocd-operator` via OLM, niet de Red Hat OpenShift GitOps-operator)
  wordt gebootstrapt door [`scripts/bootstrap/bootstrap-cluster.sh`](../scripts/bootstrap/bootstrap-cluster.sh)
  in **deze repo** — dat script installeert ook Sealed Secrets, local-path-provisioner
  en Reflector. Verhuisd hierheen vanuit `personal-news-feed-by-claude-code/deploy/bootstrap.sh`
  (2026-07-07): dat was cluster-brede bootstrap die toevallig in de eerste
  app-repo was beland, niet iets specifiek voor die app — dashboard/
  smb-timemachine leunen er net zo goed op.
- **De ArgoCD-instance draait CLUSTER-SCOPED** (sinds 2026-07-08, via
  `ARGOCD_CLUSTER_CONFIG_NAMESPACES=argocd` op de operator-Subscription):
  hij mag namespaces zelf aanmaken (`CreateNamespace=true` werkt echt) en
  beheert ook cluster-scoped objecten (Namespaces, ClusterRoles) gewoon
  uit git. Trade-off — de controller heeft hiermee praktisch cluster-admin —
  is een bewuste keuze: het cluster is stateless opgezet, dus de vangrails
  zijn git-revert en een reproduceerbare rebuild, niet RBAC. Zie de
  volledige afweging in
  [`manifests/cluster-bootstrap/argocd-operator-subscription.yaml`](../manifests/cluster-bootstrap/argocd-operator-subscription.yaml).
- **App-of-apps-patroon** (sinds 2026-07-08): één root-Application
  ([`manifests/root-app/root-application.yaml`](../manifests/root-app/root-application.yaml))
  beheert alles in `manifests/root-app/apps/` — de 4 app-Applications, de
  PR-preview-ApplicationSet, de `github-pr-token`-SealedSecret en
  preview-ns-labeller's Deployment + RBAC. Vier apps:
  - `personal-news-feed` (manifests uit `personal-news-feed-by-claude-code` repo)
  - `softwarefactory-dashboard` (manifests uit `software-factory` repo, `deploy/base`)
  - `smb-timemachine` (manifests uit **deze** repo, `manifests/smb-timemachine`)
  - `agent-access` (manifests uit **deze** repo, `manifests/agent-access` —
    read-only agent-credential, zie [access-and-credentials.md](access-and-credentials.md))

  De enige imperatieve stap na `bootstrap-cluster.sh` is de root-Application
  zelf applyen — [`scripts/bootstrap/bootstrap-apps.sh`](../scripts/bootstrap/bootstrap-apps.sh).

  (YouTrack was hier eerder ook een vierde app — verwijderd 2026-07-08, de
  Software Factory gebruikt sinds de Postgres-tracker-migratie geen YouTrack
  meer.)

  Robbert wil op termijn alle infra hier hebben, ook app-specifieke deploy-
  manifesten (niet alleen de cluster-brede lijmlaag). SMB/Time-Machine is
  daarvan een voorbeeld: volledig statisch (geen CI-image-bump, geen preview-
  koppeling), dus zonder complicaties te verplaatsen. `personal-news-feed`
  en `softwarefactory-dashboard` blijven voorlopig in hun eigen repo — hun
  CI bumpt de image-tag in dezelfde commit als de build, en personal-news-
  feed's PR-previews zijn tightly coupled aan per-PR-branch-manifesten in
  dat repo. Verhuizen kan, maar vereist een cross-repo GitHub-token voor CI
  én (voor personal-news-feed) een herontwerp van het preview-mechanisme —
  bewust nog niet gedaan.
- **Historie — waarom namespace-aanmaak vroeger een handmatige stap was**: tot 2026-07-08
  draaide de instance in "namespaced mode". De operator houdt dan een actieve allow-list bij
  (secret `argocd-default-cluster-config`, veld `namespaces`) die zichzelf pas vult ná het zien
  van een al-bestaande namespace mét het label `argocd.argoproj.io/managed-by=argocd` — dus een
  Application kon een namespace nooit voor het eerst zelf aanmaken, ongeacht RBAC (kip-en-ei,
  empirisch geverifieerd met een echte test-PR; extra RBAC zoals
  `manifests/cluster-bootstrap/argocd-namespace-creator-rbac.yaml` hielp aantoonbaar niet — dat
  manifest is bewaard als referentie maar wordt niet meer ge-apply'd). Elke nieuwe namespace was
  daardoor een handmatige/gescripte prereq. De cluster-scoped mode (zie hierboven) heft die
  allow-list op; zie [cluster-inventory.md](cluster-inventory.md) §1 voor de oude onderbouwing.
- **Sealed Secrets**: elke app committed een `SealedSecret` in git, versleuteld met het
  publieke cert van de sealed-secrets-controller. De **private key** leeft alleen in-cluster
  (`kube-system`, secret met label `sealedsecrets.bitnami.com/sealed-secrets-key`) — die
  overleeft een reinstall NIET tenzij je 'm vooraf backupt. Zie
  [backup-and-restore.md](backup-and-restore.md).

## Wat waar staat

| Wat | Waar |
|---|---|
| OpenShift-installer, ISO, pull-secret, install-config, admin-kubeconfig | `~/okd-sno/` (lokaal, niet in git). Installer/ISO herdownloaden: [download-install-tools.md](download-install-tools.md); pull-secret hoort ook in 1Password |
| ISO-buildscript voor disaster recovery | [`scripts/install/build-okd-sno.sh`](../scripts/install/build-okd-sno.sh) in **deze repo** — `~/build-okd-sno.sh` is sinds 2026-07-07 alleen nog een dunne wrapper ernaartoe, geen aparte kopie meer |
| Cluster-bootstrap (ArgoCD, Sealed Secrets, storage, Reflector) | [`scripts/bootstrap/bootstrap-cluster.sh`](../scripts/bootstrap/bootstrap-cluster.sh) in **deze repo** |
| App-specifieke bootstrap (namespace, app-secrets, Application) | eigen repo per app (`deploy/bootstrap.sh` of gewoon `oc apply`) |
| App-manifesten + Applications | eigen repo per app (`deploy/`) |
| Node-level MachineConfigs, backup-scripts, playbooks | **deze repo** |

**Waarom `~/okd-sno/` niet gewoon een submap van deze repo is (met `.gitignore`
voor het gegenereerde spul, zoals `secrets.env` in de andere repo's):** deze
repo, `personal-news-feed-by-claude-code` en `software-factory` staan alle
drie op **PUBLIC** GitHub. Bij die andere repo's is een `.gitignore`-misser
vervelend (een app-token lekt, roteer je). `~/okd-sno` bevat `pull-secret.txt`
(Red Hat-account) en `sno/auth/kubeconfig`/`kubeadmin-password`
(cluster-admin) — een misser daar zet cluster-admin permanent publiek, tot
je de git-historie herschrijft én alle credentials roteert. Fysieke scheiding
is een harde grens die niet van een correcte regel afhangt; bewust zo
gehouden (besproken en herbevestigd op 2026-07-07).
