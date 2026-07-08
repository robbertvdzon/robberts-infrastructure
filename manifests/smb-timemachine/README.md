# SMB / Time Machine share

Deelt een map uit als Samba-share met Time-Machine-ondersteuning, zodat
MacBooks op het thuisnetwerk erop kunnen backuppen.

**Status: getest en werkend, definitieve opzet sinds 2026-07-08.** Draait op
een externe USB-HDD ("Verbatim Desktop HDD 3.0", 3.7TB, exFAT), gemount op
`/var/mnt/external-hdd` via [`../machineconfigs/51-external-hdd-mount.yaml`](../machineconfigs/51-external-hdd-mount.yaml).
Bewuste keuze voor extern/exFAT i.p.v. de voormalige interne 4TB-schijf: bij
een kapotte OpenShift-machine kan de schijf losgekoppeld en direct op een Mac
aangesloten worden — dat werkt niet met een schijf die in de server vastzit.
De interne 4TB-schijf (`/var/mnt/localpv`) is hierdoor overbodig geworden en
z'n MachineConfig (`50-local-storage-mount`) is verwijderd.

Geverifieerd vanaf een macOS-client: SMB-auth, mounten, schrijven/lezen, en
Bonjour/mDNS-advertentie (`_adisk._tcp` — de service waarmee Time Machine
netwerkschijven ontdekt), inclusief bevestiging dat data daadwerkelijk op de
exFAT-partitie landt (`df` binnen de pod toont `/dev/sdc2`, niet de OS-schijf).
Nog **niet** getest: een volledige, langlopende Time Machine-backup (alleen
handmatige bestandsoperaties via `mount_smbfs`). Zie
[../../docs/smb-timemachine-test-procedure.md](../../docs/smb-timemachine-test-procedure.md)
voor hoe je dat verifieert.

Eén ding is bewust anders dan bij een gewone XFS-schijf: `SAMBA_VOLUME_CONFIG_timemachine`
gebruikt `fruit:metadata = netatalk` + `fruit:resource = file` i.p.v.
`streams_xattr` — exFAT ondersteunt geen xattrs, `streams_xattr` heeft die
nodig.

## Waarom deze keuzes

- **`ghcr.io/servercontainers/samba`**: heeft Time-Machine-support
  (`fruit:time machine`, Avahi/mDNS-advertentie) als env-vars, geen
  handgeschreven `smb.conf` nodig.
- **`hostNetwork: true`**: Time Machine ontdekt de share via Bonjour/mDNS
  (multicast) — dat werkt niet betrouwbaar door de pod-overlay heen. Met
  hostNetwork draait de share op het node-IP (`192.168.178.64`), rechtstreeks
  bereikbaar op het LAN.
- **hostPath naar `/var/mnt/external-hdd`**: geen aparte StorageClass, gewoon
  direct de gemounte schijf (zie [../../docs/architecture.md](../../docs/architecture.md)).
- **initContainer `init-permissions`**: kubelet maakt een lege hostPath-
  subPath-directory aan als `root:root 0700` — ontoegankelijk voor de
  gemapte SMB-user. Getest: zonder deze initContainer geeft `mount_smbfs`
  `Permission denied` op een verse schijf/na een schijf-migratie. Met de
  initContainer (chown naar UID 1000, de gemapte `robbert`-user) werkt het
  zelfherstellend, geen handmatige `ssh ... chown` nodig.

## Gevonden en gefixt tijdens het testen (nuttig bij toekomstige wijzigingen)

1. `ACCOUNT_<naam>` **is** het wachtwoord voor deze image — er bestaat geen
   aparte `SAMBA_PASSWORD`-variabele (die wordt stilzwijgend genegeerd). Eerste
   poging gaf `Authentication error` tot dit duidelijk werd.
2. Image-tag `:smbd` bestaat niet, de juiste tag is `:latest`.
3. `hostNetwork: true` + vaste poorten (445/5353) verdraagt geen
   `RollingUpdate` — de oude en nieuwe pod botsen op dezelfde node-poorten
   ("didn't have free ports"). Deployment-strategy staat daarom op `Recreate`.
4. Container heeft `securityContext.privileged: true` nodig (niet genoeg aan
   alleen de SCC-grant) — anders crasht `avahi-daemon` op `cap_set_proc()
   failed: Operation not permitted` en werkt Bonjour-discovery niet.
5. Permissie-fix hierboven (initContainer).

## Installeren — via ArgoCD (onderdeel van de root-app)

Alles hier (namespace, ServiceAccount, RoleBinding voor de privileged-SCC,
SealedSecret, Deployment) staat in git en wordt door ArgoCD gesynct. De
Application-pointer zelf staat sinds de app-of-apps-consolidatie (2026-07-08)
niet meer hier, maar in
[`../root-app/apps/smb-timemachine-application.yaml`](../root-app/apps/smb-timemachine-application.yaml)
— zie [`../root-app/root-application.yaml`](../root-app/root-application.yaml)
voor hoe je die (samen met de andere 2 apps) in één keer installeert.

Eenmalige cluster-scoped prereq — **blijft verplicht**, ook na de
namespace-creator-RBAC-fix van 2026-07-08: die geeft ArgoCD wel het recht om
een namespace te *beheren* zodra 'ie al bestaat en gelabeld is, maar een
Application kan een namespace nooit voor het eerst zelf aanmaken op deze
cluster (geverifieerd met een echte test-PR — zie
[../../docs/cluster-inventory.md](../../docs/cluster-inventory.md) §1 voor
de volledige uitleg van dat mechanisme):
```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig   # break-glass admin, zie
                                                    # ../../docs/access-and-credentials.md
oc apply -f manifests/smb-timemachine/namespace.yaml
```

Daarna volledig autonoom (self-heal aan, prune aan). Wachtwoord wijzigen: zie
[ROTATE-PASSWORD.md](ROTATE-PASSWORD.md) — ook dat gaat via git + ArgoCD, niet
via een losse `oc create secret`.

Testen: zie [../../docs/smb-timemachine-test-procedure.md](../../docs/smb-timemachine-test-procedure.md).

## Bekende beperkingen

- `nodeSelector: kubernetes.io/hostname: sno.lab.vdzon.com` is hardcoded —
  klopt zolang dit een SNO-cluster blijft.
- Geen backup van de Time-Machine-data zelf (dit IS de backup-bestemming).
