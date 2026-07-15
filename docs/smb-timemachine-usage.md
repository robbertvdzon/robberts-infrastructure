# SMB / Time Machine — gebruik, permanente mount en schijfvervanging

Twee shares op dezelfde externe USB-HDD (zie
[`../manifests/smb-timemachine/deployment.yaml`](../manifests/smb-timemachine/deployment.yaml)):

- **`TimeMachine`** (`fruit:time machine = yes`) — uitsluitend voor macOS Time
  Machine. Meerdere Macs kunnen hier gewoon tegelijk op backuppen: Time
  Machine maakt zelf één `.sparsebundle`-bestand per Mac (genaamd naar de
  Mac's computernaam) in de share-root — geen aparte subfolder per machine
  nodig, dat regelt macOS zelf.
- **`ExternalHDD`** — voor al het andere: losse bestanden, andere
  backup-tools (rsync, restic, etc.). Gebruik hier per Mac een eigen subfolder
  onder `backups/`, zie sectie 3.

Beide shares staan op `192.168.178.64`, user `robbert`, wachtwoord ophalen met:
```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig
oc get secret samba-timemachine-credentials -n smb-timemachine -o jsonpath='{.data.SAMBA_PASSWORD}' | base64 -d; echo
```

## 1. Permanente mount op de MacBooks (voor de `ExternalHDD`-share)

Dit is **niet** nodig voor Time Machine zelf (die regelt zijn eigen
SMB-verbinding, zie sectie 2) — dit is voor algemeen/ander gebruik: gewoon
door Finder/Terminal benaderbaar zijn zonder elke keer handmatig te mounten.

Via een LaunchAgent die bij inloggen (en daarna elke 5 min als 't nog niet
lukte, bv. omdat wifi nog niet op was) automatisch mount. Wachtwoord staat in
de macOS Keychain, niet in een plaintext script. **Doe dit op beide
MacBooks** (identieke stappen, elke Mac heeft z'n eigen Keychain).

```bash
# 1. Wachtwoord eenmalig in de Keychain zetten (vraagt het net opgehaalde SAMBA_PASSWORD)
security add-generic-password -a robbert -s smb-sno-externalhdd -w '<wachtwoord>'

# 2. Mount-script
mkdir -p ~/bin
cat > ~/bin/mount-smb-sno.sh <<'EOF'
#!/bin/bash
MOUNTPOINT="$HOME/mnt/ExternalHDD"
mkdir -p "$MOUNTPOINT"
if ! mount | grep -q "$MOUNTPOINT"; then
  PASSWORD=$(security find-generic-password -a robbert -s smb-sno-externalhdd -w)
  mount_smbfs "//robbert:${PASSWORD}@192.168.178.64/ExternalHDD" "$MOUNTPOINT"
fi
EOF
chmod +x ~/bin/mount-smb-sno.sh

# 3. LaunchAgent: mount bij inloggen + retry elke 5 min
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.robbert.mount-smb-sno.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.robbert.mount-smb-sno</string>
  <key>ProgramArguments</key>
  <array><string>$HOME/bin/mount-smb-sno.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/mount-smb-sno.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.robbert.mount-smb-sno.plist

# 4. Direct testen (niet wachten tot de volgende login)
~/bin/mount-smb-sno.sh
ls -la ~/mnt/ExternalHDD
```

Mountpoint is bewust `~/mnt/ExternalHDD` (binnen je home-directory) i.p.v.
`/Volumes/...` — dat laatste vereist root-rechten om de map aan te maken,
`~/mnt` werkt gewoon als gebruiker. Vanuit Finder bereikbaar via **Ga → Ga
naar map… → `~/mnt/ExternalHDD`**.

Uitzetten (als je 'm ooit niet meer wil): `launchctl unload
~/Library/LaunchAgents/com.robbert.mount-smb-sno.plist`.

## 2. Time Machine instellen (per Mac, eenmalig)

1. **Systeeminstellingen → Algemeen → Time Machine → Voeg back-upschijf toe**.
2. `sno-timemachine` zou moeten verschijnen (via Bonjour). Zo niet: mount
   eerst één keer handmatig via Finder (**Ga → Verbind met server…** →
   `smb://192.168.178.64/TimeMachine`) om de credentials in de Keychain te
   krijgen, probeer daarna Time Machine opnieuw.
3. Inloggen met user `robbert` + het wachtwoord uit de secret (zie boven),
   **"Bewaar in Sleutelhanger"** aanvinken.
4. Herhaal dit op de tweede MacBook — die krijgt automatisch een eigen
   sparsebundle (andere computernaam), botst niet met de eerste.
5. Laat op beide Macs minstens één volledige backup doorlopen, en verifieer
   dat je ook kan **restoren** (vaak overgeslagen, bewijst het meest — blader
   in Time Machine door de backup, herstel een test-bestand).

Verifiëren dat beide sparsebundles er staan:
```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'ls -la /var/mnt/external-hdd/timemachine'
```

## 3. Andere backups via dezelfde schijf (`ExternalHDD`-share)

Gebruik een subfolder per Mac onder `backups/`, zodat ze elkaar niet
overschrijven. Voorbeeld met rsync:

```bash
DEST="$HOME/mnt/ExternalHDD/backups/$(scutil --get ComputerName)"
mkdir -p "$DEST/Documents"
rsync -av --delete ~/Documents/ "$DEST/Documents/"
```

Welke tool je gebruikt maakt niet uit (rsync, restic, gewoon Finder
slepen) — zolang je onder je eigen `backups/<computernaam>/` blijft, zit je
de Time Machine-share (die is en blijft uitsluitend voor Time Machine) niet
in de weg.

## 4. Snelle CLI-test (na elke wijziging aan de manifests)

```bash
# Poort bereikbaar?
nc -zv 192.168.178.64 445

# Mount + schrijf/lees-test
mkdir -p /tmp/smbtest
mount_smbfs "//robbert:<wachtwoord>@192.168.178.64/ExternalHDD" /tmp/smbtest
ls -la /tmp/smbtest
echo "test-$(date +%s)" > /tmp/smbtest/test.txt
cat /tmp/smbtest/test.txt
rm /tmp/smbtest/test.txt
umount /tmp/smbtest

# Bonjour/mDNS-advertentie (Time Machine ontdekt hiermee netwerkschijven)
dns-sd -B _adisk._tcp local
# verwacht: "Add ... sno-timemachine" binnen een paar seconden — Ctrl-C om te stoppen
```

## 5. USB-HDD vervangen door een nieuwe

Uitgangspunt: data hoeft niet mee te verhuizen (nieuwe schijf mag leeg zijn),
maar de mount + Samba-share moeten daarna weer gewoon werken. **Gevolg voor
Time Machine: de eerste backup na de wissel is weer een volledige backup**
(macOS ziet een lege bestemming) — niet te vermijden als data niet meeverhuist.

### 5.1 Nieuwe schijf voorbereiden (op een Mac)

1. Sluit de nieuwe externe HDD aan op een Mac.
2. **Schijfhulpprogramma** → selecteer de hele schijf (bovenste item, niet
   het volume eronder) → **Wis**.
3. Naam: `data` (zelfde label als de oude, niet verplicht maar consistent).
4. Formaat: **ExFAT**. Schema: **GUID-partitieschema**.
5. Klik Wis.

### 5.2 Fysiek wisselen

```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'sudo shutdown -h now'
# wachten tot ping niet meer reageert, dan pas loskoppelen
```
PC uitzetten, oude USB-HDD eraf, nieuwe erop, PC weer aan.

### 5.3 by-id-pad van de nieuwe schijf opzoeken

```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'ls -la /dev/disk/by-id/ | grep -i usb'
```
Zoek de regel die naar de exFAT-datapartitie wijst. Bij een GUID-partitieschema
staat de eigenlijke volume-partitie meestal op `-part2` (part1 is de kleine
EFI-partitie die macOS er automatisch bij maakt) — net als bij de huidige
schijf, maar **controleer het echt**, ga er niet vanuit.

### 5.4 MachineConfig bijwerken

Pas [`../manifests/machineconfigs/51-external-hdd-mount.yaml`](../manifests/machineconfigs/51-external-hdd-mount.yaml)
aan:
- `What=` → het nieuwe by-id-pad uit stap 5.3.
- De toelichting bovenaan het bestand (schijfmodel/serienummer) bijwerken
  zodat die niet meer naar de oude schijf verwijst.

Commit + push.

### 5.5 Toepassen — **dit reboot de node** (paar minuten downtime voor alles)

```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig
oc apply -f manifests/machineconfigs/51-external-hdd-mount.yaml
oc get mcp master -w   # wacht tot UPDATED=True, dan Ctrl-C
```

### 5.6 Mount + permissies verifiëren

Een verse schijf heeft nog geen `timemachine`-submap met de juiste
eigenaar — dit is exact het scenario dat sectie 6 hieronder normaal
gesproken *simuleert*; nu is het de echte situatie:

```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'df -h /var/mnt/external-hdd'
oc rollout restart deployment/samba-timemachine -n smb-timemachine
oc rollout status deployment/samba-timemachine -n smb-timemachine
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'ls -la /var/mnt/external-hdd/'
# timemachine-map moet uid/gid 1000 tonen, niet root:root
```

Zo niet: check `oc logs -n smb-timemachine -c init-permissions
deploy/samba-timemachine`.

### 5.7 Functioneel testen en Time Machine opnieuw koppelen

1. Draai sectie 4 (snelle CLI-test) opnieuw.
2. Op **beide** Macs: Systeeminstellingen → Time Machine → verwijder de oude
   schijf uit de lijst (staat er nog, maar wijst nu naar een lege
   bestemming) → voeg 'm opnieuw toe zoals in sectie 2. Verwacht: eerste
   backup erna is weer volledig (zie boven).
3. De permanente `ExternalHDD`-mount uit sectie 1 hoeft niet opnieuw
   ingesteld te worden — die verbindt gewoon opnieuw zodra de share weer
   bereikbaar is, alleen de inhoud is nu leeg.

### 5.8 Opruimen

Werk het schijfmodel/serienummer ook bij in
[`../manifests/smb-timemachine/README.md`](../manifests/smb-timemachine/README.md)
(huidige tekst noemt nog expliciet "Verbatim Desktop HDD 3.0") zodat
toekomstige troubleshooting niet uitgaat van de oude schijf.

## 6. "Verse schijf"-simulatie (om de initContainer-permissiefix te testen zónder een schijf te vervangen)

```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'sudo rm -rf /var/mnt/external-hdd/timemachine'
oc rollout restart deployment/samba-timemachine -n smb-timemachine
oc rollout status deployment/samba-timemachine -n smb-timemachine

# moet root:root NIET meer tonen na een paar seconden:
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'ls -la /var/mnt/external-hdd/'
```

Verwacht: de `timemachine`-map bestaat, eigenaar is uid 1000 (`core` op
host-niveau, `robbert` binnen de container), mode `0700`. Daarna moet sectie 4
(mount-test) weer slagen. Zo niet: check
`oc logs -n smb-timemachine -c init-permissions deploy/samba-timemachine`.
