# Architectuur

## Hardware

- ASUS PRIME H410M-K, Intel/AMD64
- 32GB RAM
- `/dev/sda` — 240GB SATA SSD, OS-schijf (RHCOS/SCOS)
- `/dev/sdb` — 4TB SATA-schijf, gemount op `/var/mnt/localpv` (wordt op termijn 12TB, zie
  [disk-4tb-to-12tb-migration.md](disk-4tb-to-12tb-migration.md))
- 1Gbps bedraad ethernet, vast IP `192.168.178.64` via DHCP-reservation op de Ziggo router (MAC `24:4B:FE:82:0D:4D`)

## Cluster

- OKD single-node (SNO), SCOS-variant, versie `4.21.0-okd-scos.10`
- Cluster-naam `sno`, base domain `lab.vdzon.com`
- OVN-Kubernetes, IPv4-only (IPv6 bewust uitgezet — zie install-quirks hieronder)
- Enige StorageClass: `local-path` (rancher.io/local-path), path `/var/lib/local-path-provisioner`
  op de **kleine SSD** — de 4TB-schijf wordt momenteel niet door Kubernetes-storage gebruikt.

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

1. **`50-local-storage-mount`** — mount de 4TB-schijf op `/var/mnt/localpv` (XFS,
   `/dev/disk/by-id/wwn-...`).
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
  wordt gebootstrapt door `personal-news-feed-by-claude-code/deploy/bootstrap.sh` — dat script
  installeert ook Sealed Secrets, local-path-provisioner en Reflector.
- Geen app-of-apps-patroon: elke app heeft een eigen `Application`-resource die **los**
  `oc apply`'d wordt (geen root-Application die ze allemaal aanmaakt). Vier apps:
  - `personal-news-feed` (uit `personal-news-feed-by-claude-code` repo)
  - `youtrack` (uit `software-factory` repo, `deploy/youtrack`)
  - `softwarefactory-dashboard` (uit `software-factory` repo, `deploy/base`)
  - `smb-timemachine` (uit **deze** repo, `manifests/smb-timemachine`) — de enige
    app die vanuit `robberts-infrastructure` zelf gesynct wordt in plaats van
    vanuit een app-repo
- **Sealed Secrets**: elke app committed een `SealedSecret` in git, versleuteld met het
  publieke cert van de sealed-secrets-controller. De **private key** leeft alleen in-cluster
  (`kube-system`, secret met label `sealedsecrets.bitnami.com/sealed-secrets-key`) — die
  overleeft een reinstall NIET tenzij je 'm vooraf backupt. Zie
  [backup-and-restore.md](backup-and-restore.md).

## Wat waar staat

| Wat | Waar |
|---|---|
| OpenShift-installer, ISO, pull-secret, install-config, admin-kubeconfig | `~/okd-sno/` (lokaal, niet in git) |
| ISO-buildscript voor disaster recovery | `~/build-okd-sno.sh` (let op: **niet** in `~/okd-sno/` zoals `handoff.md` zegt — makkelijk te missen) |
| App-bootstrap (ArgoCD, Sealed Secrets, storage, Reflector) | `personal-news-feed-by-claude-code/deploy/bootstrap.sh` |
| App-manifesten + Applications | eigen repo per app (`deploy/`) |
| Node-level MachineConfigs, backup-scripts, playbooks | **deze repo** |
