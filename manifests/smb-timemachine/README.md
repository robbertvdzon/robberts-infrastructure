# SMB / Time Machine share

Deelt een map op de databaseschijf (`/var/mnt/localpv/timemachine`) uit als
Samba-share met Time-Machine-ondersteuning, zodat MacBooks op het
thuisnetwerk erop kunnen backuppen.

**Status: getest en werkend (2026-07-06).** Geverifieerd vanaf een macOS-client:
SMB-auth, mounten, schrijven/lezen, en Bonjour/mDNS-advertentie
(`_adisk._tcp` — de service waarmee Time Machine netwerkschijven ontdekt).
Nog **niet** getest: een volledige, langlopende Time Machine-backup (alleen
handmatige bestandsoperaties via `mount_smbfs`). Zie
[../../docs/smb-timemachine-test-procedure.md](../../docs/smb-timemachine-test-procedure.md)
voor hoe je dat verifieert en hoe je dit zelf opnieuw kan testen.

## Waarom deze keuzes

- **`ghcr.io/servercontainers/samba`**: heeft Time-Machine-support
  (`fruit:time machine`, Avahi/mDNS-advertentie) als env-vars, geen
  handgeschreven `smb.conf` nodig.
- **`hostNetwork: true`**: Time Machine ontdekt de share via Bonjour/mDNS
  (multicast) — dat werkt niet betrouwbaar door de pod-overlay heen. Met
  hostNetwork draait de share op het node-IP (`192.168.178.64`), rechtstreeks
  bereikbaar op het LAN.
- **hostPath naar `/var/mnt/localpv`**: geen aparte StorageClass, gewoon
  direct de gemounte schijf (zie [../../docs/architecture.md](../../docs/architecture.md)
  voor waarom die schijf toch al vrij is).
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

## Installeren — via ArgoCD (4e Application)

Alles hier (namespace, ServiceAccount, RoleBinding voor de privileged-SCC,
SealedSecret, Deployment) staat nu in git en wordt door ArgoCD gesynct —
**niet** meer los `oc apply -k`'d. De enige stap die nog met het admin-
account moet (ArgoCD kan zichzelf geen Application geven):

```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig   # break-glass admin, zie
                                                    # ../../docs/access-and-credentials.md
oc apply -f manifests/smb-timemachine/argocd-application.yaml
```

Daarna volledig autonoom (self-heal aan, prune aan). Wachtwoord wijzigen: zie
[ROTATE-PASSWORD.md](ROTATE-PASSWORD.md) — ook dat gaat via git + ArgoCD, niet
via een losse `oc create secret`.

Testen: zie [../../docs/smb-timemachine-test-procedure.md](../../docs/smb-timemachine-test-procedure.md).

## Bekende beperkingen

- `nodeSelector: kubernetes.io/hostname: sno.lab.vdzon.com` is hardcoded —
  klopt zolang dit een SNO-cluster blijft.
- Geen backup van de Time-Machine-data zelf (dit IS de backup-bestemming).
