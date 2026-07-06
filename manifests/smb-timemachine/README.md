# SMB / Time Machine share

Deelt een map op de databaseschijf (`/var/mnt/localpv/timemachine`) uit als
Samba-share met Time-Machine-ondersteuning, zodat MacBooks op het
thuisnetwerk erop kunnen backuppen.

Status: **eerste opzet, nog niet getest** op een echte Time Machine-backup.
Verifieer na deploy met een macOS-client (Systeemvoorkeuren → Time Machine →
Kies back-upschijf → moet `sno-timemachine` tonen via Bonjour) voordat je
erop vertrouwt als enige backup-methode.

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

## Installeren

```bash
# 1. SCC voor hostPath-toegang (zelfde patroon als local-path-provisioner in
#    personal-news-feed-by-claude-code/deploy/bootstrap.sh)
oc apply -k manifests/smb-timemachine/   # maakt namespace + serviceaccount + deployment
oc adm policy add-scc-to-user privileged -z samba-timemachine -n smb-timemachine

# 2. Credentials (niet in git als plaintext)
cp manifests/smb-timemachine/secret-smb-credentials.example.yaml \
   manifests/smb-timemachine/secret-smb-credentials.yaml
# bewerk secret-smb-credentials.yaml, vul een echt wachtwoord in
oc apply -f manifests/smb-timemachine/secret-smb-credentials.yaml

# 3. Restart zodat de pod de SCC + secret oppikt
oc rollout restart deployment/samba-timemachine -n smb-timemachine
```

## Bekende beperkingen / dingen om te checken

- `nodeSelector: kubernetes.io/hostname: sno.lab.vdzon.com` is hardcoded —
  klopt zolang dit een SNO-cluster blijft.
- Geen backup van de Time-Machine-data zelf (dit IS de backup-bestemming).
  Als je zeker wil zijn: overweeg periodiek een kopie van
  `/var/mnt/localpv/timemachine` naar iets anders (bv. cloud-storage).
- Nog niet gewired in ArgoCD — wordt los `oc apply -k`'d, niet automatisch
  gesynct. Kan later als 4e Application toegevoegd worden als dat gewenst is.
