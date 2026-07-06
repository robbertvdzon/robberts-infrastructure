# SMB / Time Machine — testprocedure

Twee niveaus: een snelle CLI-test (geen macOS-GUI nodig, goed voor na elke
wijziging aan de manifests) en een echte Time Machine-backup-test (eenmalig,
met de hand op een Mac).

## 1. Snelle CLI-test (macOS, vanaf elke Mac op het LAN)

```bash
# Poort bereikbaar?
nc -zv 192.168.178.64 445

# Mount + schrijf/lees-test
mkdir -p /tmp/smbtest
mount_smbfs "//robbert:<wachtwoord>@192.168.178.64/TimeMachine" /tmp/smbtest
ls -la /tmp/smbtest
echo "test-$(date +%s)" > /tmp/smbtest/test.txt
cat /tmp/smbtest/test.txt
rm /tmp/smbtest/test.txt
umount /tmp/smbtest

# Bonjour/mDNS-advertentie (Time Machine ontdekt hiermee netwerkschijven)
dns-sd -B _adisk._tcp local
# verwacht: "Add ... sno-timemachine" binnen een paar seconden — Ctrl-C om te stoppen
```

## 2. "Verse schijf"-simulatie (om de initContainer-permissiefix te verifiëren)

Dit is wat er gebeurt na een schijf-migratie (zie
[disk-4tb-to-12tb-migration.md](disk-4tb-to-12tb-migration.md)) of een cluster-
reinstall met een lege schijf. Simuleer het zonder echt een schijf te vervangen:

```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'sudo rm -rf /var/mnt/localpv/timemachine'
oc rollout restart deployment/samba-timemachine -n smb-timemachine
oc rollout status deployment/samba-timemachine -n smb-timemachine

# moet root:root NIET meer tonen na een paar seconden:
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'ls -la /var/mnt/localpv/'
```

Verwacht: de `timemachine`-map bestaat, eigenaar is uid 1000 (`core` op
host-niveau, `robbert` binnen de container), mode `0700`. Daarna moet stap 1
(mount-test) weer slagen. Zo niet: check
`oc logs -n smb-timemachine -c init-permissions deploy/samba-timemachine`.

## 3. Echte Time Machine-backup (met de hand, eenmalig te verifiëren)

1. Op de Mac: **Systeemvoorkeuren → Time Machine → Kies back-upschijf**.
2. `sno-timemachine` zou moeten verschijnen (via Bonjour, zie stap 1). Zo niet:
   Finder → Netwerk, of `smb://192.168.178.64/TimeMachine` handmatig via
   Finder → Ga naar → Verbind met server.
3. Inloggen met de credentials uit `secret-smb-credentials.yaml`.
4. Start een backup, laat 'm minstens één keer volledig doorlopen.
5. Verifieer op de node dat er data staat:
   ```bash
   ssh -i ~/.ssh/okd-sno core@192.168.178.64 'du -sh /var/mnt/localpv/timemachine'
   ```
6. **Verifieer dat je ook kan restoren** — dit is de stap die het vaakst
   overgeslagen wordt en het meest bewijst. Open Time Machine, blader door de
   backup, herstel een test-bestand.

Pas na een geslaagde stap 3–6 is dit een betrouwbare backup-bestemming — de
CLI-testen in stap 1–2 bewijzen alleen dat de share technisch werkt, niet dat
een Time Machine-backup er ook echt goed op wegschrijft/leesbaar terugkomt.
