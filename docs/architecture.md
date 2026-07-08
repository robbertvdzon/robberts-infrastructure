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
  app-repo was beland, niet iets specifiek voor die app — youtrack/dashboard/
  smb-timemachine leunen er net zo goed op. Elke app heeft daarna nog een
  eigen, kortere app-specifieke bootstrap-stap (namespace, app-secrets, de
  Application zelf) — zie bv. `personal-news-feed-by-claude-code/deploy/bootstrap.sh`.
- Geen app-of-apps-patroon: elke app heeft een eigen `Application`-resource die **los**
  `oc apply`'d wordt (geen root-Application die ze allemaal aanmaakt). Vier apps:
  - `personal-news-feed` (uit `personal-news-feed-by-claude-code` repo)
  - `youtrack` (uit **deze** repo, `manifests/youtrack`)
  - `softwarefactory-dashboard` (uit `software-factory` repo, `deploy/base`)
  - `smb-timemachine` (uit **deze** repo, `manifests/smb-timemachine`)

  Robbert wil op termijn alle infra hier hebben, ook app-specifieke deploy-
  manifesten (niet alleen de cluster-brede lijmlaag). YouTrack is daarvan de
  eerste (2026-07-07): volledig statisch (geen CI-image-bump, geen preview-
  koppeling), dus zonder complicaties te verplaatsen. `personal-news-feed`
  en `softwarefactory-dashboard` blijven voorlopig in hun eigen repo — hun
  CI bumpt de image-tag in dezelfde commit als de build, en personal-news-
  feed's PR-previews zijn tightly coupled aan per-PR-branch-manifesten in
  dat repo. Verhuizen kan, maar vereist een cross-repo GitHub-token voor CI
  én (voor personal-news-feed) een herontwerp van het preview-mechanisme —
  bewust nog niet gedaan.
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
