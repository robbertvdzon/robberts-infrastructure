# Disaster recovery playbook — OpenShift opnieuw opbouwen

Doel: na deze procedure werkt alles weer exact zoals nu — zelfde URLs, zelfde
data, zelfde secrets, zelfde storage-indeling.

Lees eerst [architecture.md](architecture.md) als je niet weet hoe de stukken
in elkaar zitten.

## 0. Vóór je begint

- [ ] `./scripts/backup/backup-all.sh` gedraaid en de `backups/<timestamp>/`
      map gekopieerd naar iets buiten deze laptop. Zie
      [backup-and-restore.md](backup-and-restore.md). **Sla deze stap niet
      over** — zonder de sealed-secrets key ben je alle secrets kwijt.
- [ ] Als de 4TB-schijf data bevat die je wil behouden (bv. Time Machine
      backups): zie [disk-4tb-to-12tb-migration.md](disk-4tb-to-12tb-migration.md)
      voor hoe je die veilig aftapt vóór de reinstall, of laat de schijf
      gewoon zitten — een OpenShift-reinstall raakt `/dev/sdb` niet aan zolang
      je alleen `/dev/sda` (de OS-schijf) opnieuw installeert.
- [ ] `oc get application -n argocd` en `oc get pods -A` — noteer de huidige
      staat zodat je na de reinstall kan vergelijken.
- [ ] Benodigdheden voor het ISO-bouwen aanwezig: `jq` (`brew install jq`),
      Docker Desktop draaiend (voor de `coreos-installer`-container).
      `openshift-install`/`oc`/`kubectl`/`scos-live.iso` niet (meer) in
      `~/okd-sno/`? Zie [download-install-tools.md](download-install-tools.md)
      voor de exacte download-commando's — en `pull-secret.txt` staat in
      1Password (zie datzelfde document), niet alleen lokaal.

## 1. Cluster installeren

Dit is de fase met de meeste bekende valkuilen — 6 pogingen en ~18 uur bij de
originele install. Zie [install-troubleshooting.md](install-troubleshooting.md)
voor de volledige symptoom→oorzaak→fix-tabel als iets onderweg misgaat; hier
alleen de happy path.

Volg [`scripts/install/build-okd-sno.sh`](../scripts/install/build-okd-sno.sh)
(uit deze repo — werkt vanuit `~/okd-sno` als workdir voor de grote
binaries/ISO/secrets, die horen niet in git) — dat script bakt de ignition
met de install-quirks die tijdens de originele install zijn gevonden:

1. **Static ethernet + IPv6 disabled in de ignition zelf** (niet als
   MachineConfig — die werken pas ná bootstrap, te laat voor de Ziggo
   IPv6-SLAAC-problemen, zie install-troubleshooting.md Probleem 3).
2. **Geen kernel-arg `ipv6.disable=1`** — dat breekt OVN (probeert
   `sysctl -w net.ipv6.conf.all.forwarding=0` te zetten op een path dat niet
   bestaat zonder de kernel-module).
3. **Hostname in de ignition** (`sno.lab.vdzon.com`) — anders hangt
   `node-valid-hostname.service` op bootkube (Probleem 4).

Na het booten van `scos-live.iso`:
```bash
ssh-keygen -R 192.168.178.64   # oude host-key weg als dit een herinstall is
ssh -i ~/.ssh/okd-sno core@192.168.178.64
```
Verifieer dat de ignition-fixes echt actief zijn vóórdat je verder gaat:
```bash
hostname            # moet sno.lab.vdzon.com zijn, NIET localhost.localdomain
ip -6 addr show      # moet leeg zijn voor de ethernet-interface (geen IPv6)
```

Als `/dev/sda` nog data van een vorige install heeft (LVM van een oude
Ubuntu-install blokkeert anders `install-to-disk`, zie
install-troubleshooting.md Probleem 2 — de `vgchange`-stap is essentieel en
ontbrak lang in dit playbook):
```bash
sudo vgs                          # zoek de VG-naam, bv. "ubuntu-vg"
sudo vgchange -an <vg-naam>
sudo dmsetup remove_all 2>/dev/null
sudo wipefs -a /dev/sda
```

`install-to-disk.service` pakt de wipe binnen enkele seconden op (retry-loop).
Wacht op het auto-reboot-bericht en haal **direct** de USB-stick eruit
(anders boot 'ie weer van USB in plaats van de SSD).

Volg de installatie vanaf de MacBook:
```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig
./openshift-install --dir=sno wait-for install-complete --log-level=info
```
`connection refused`-meldingen in de eerste 10-15 min zijn normaal. Na
"Install complete!":
```bash
oc get nodes
oc get co   # alle operators Available=True, Degraded=False
```

**Verwacht**: `/dev/sdb` (de 4TB/12TB-schijf) is nog fysiek aanwezig maar
NIET gemount — dat gebeurt in de volgende stap.

## 2. Node-level MachineConfigs

```bash
./scripts/machineconfig/apply-machineconfigs.sh
```

Dit mount de databaseschijf op `/var/mnt/localpv` en fixt de DNS
search-domain-bug (zonder deze stap: console 60s+ traag, zie
[architecture.md](architecture.md)). MCO reboot de node — wacht tot
`oc get mcp master` weer `UPDATED=True` toont.

Verifieer:
```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'df -h /var/mnt/localpv; cat /etc/resolv.conf'
```

## 3. ArgoCD, Sealed Secrets, storage, Reflector

Cluster-breed, niet app-specifiek — leeft daarom in déze repo, niet in een
app-repo (zie [architecture.md](architecture.md)):

```bash
./scripts/bootstrap/bootstrap-cluster.sh
```

**Stop hier zodra je in de output "[3/7] Sealed Secrets controller" ziet
verschijnen en de rollout klaar is** (of run het script gewoon door — het is
idempotent, je kan het na de key-restore gewoon nog een keer draaien):

```bash
# Direct na de sealed-secrets-controller install, VOORDAT je verder gaat:
./scripts/backup/restore-sealed-secrets-key.sh <backup>/sealed-secrets-keys.yaml
```

Draai daarna `./scripts/bootstrap/bootstrap-cluster.sh` nogmaals (idempotent)
om de resterende stappen (storage, Reflector) af te maken.

## 4. Apps

Elke app heeft nu een eigen, kortere bootstrap-stap (checkt zelf of stap 3
al gedraaid is):

```bash
cd ~/git/personal-news-feed-by-claude-code
./deploy/bootstrap.sh
```

YouTrack en het softwarefactory-dashboard hebben geen eigen bootstrap-script
— die Applications moet je los `apply`'en:

```bash
cd ~/git/softwarefactory
oc apply -n argocd -f deploy/argocd-application.yaml
oc apply -n argocd -f deploy/youtrack-application.yaml
```

## 5. Verifiëren dat de secrets goed zijn aangekomen

```bash
oc get sealedsecrets -A
oc get secrets -n personal-news-feed newsfeed-api-keys
oc get secrets -n software-factory softwarefactory-dashboard-secrets
```

Als deze er niet binnen een paar minuten zijn (ArgoCD sync + controller
decrypt): check `oc logs -n kube-system deploy/sealed-secrets-controller` op
decrypt-errors — dat betekent dat de key-restore (stap 3) niet gelukt is en je
alsnog moet resealen (zie [backup-and-restore.md](backup-and-restore.md)).

## 6. Read-only agent-toegang (Claude Code, tester/refiner-agents, Telegram-assistent)

```bash
oc apply -k manifests/agent-access/
```

Genereer daarna een nieuw token + kubeconfig (zie
[access-and-credentials.md](access-and-credentials.md)) en zet dat pad in
`SF_KUBECONFIG` in `software-factory/secrets.env` — dit gebruik je vanaf nu
voor al het niet-menselijke `oc`-gebruik, **niet** het admin-kubeconfig.

## 7. SMB / Time Machine share

Vierde ArgoCD Application, vanuit deze repo zelf (niet vanuit een app-repo):

```bash
oc apply -f manifests/smb-timemachine/argocd-application.yaml
```

Verder volledig via git/ArgoCD — zie
[../manifests/smb-timemachine/README.md](../manifests/smb-timemachine/README.md).

## 8. Externe, niet-gescripte stukken

Deze zijn NIET cluster-afhankelijk en horen dus al te kloppen — controleer
alleen dat ze niet per ongeluk gewijzigd zijn. Zie
[manual-external-steps.md](manual-external-steps.md) voor de volledige uitleg:

- [ ] One.com DNS: `A *.apps.sno.lab.vdzon.com`, `A api(-int).sno.lab.vdzon.com`
      → `192.168.178.64`; `AAAA *.vdzon.com` staat UIT.
- [ ] Ziggo router: DHCP-reservation MAC `24:4B:FE:82:0D:4D` → `192.168.178.64`.
- [ ] Cloudflare Tunnels: tokens zitten al in de (restored) SealedSecrets, dus
      als stap 3 gelukt is hoef je hier niets te doen. Alleen als je NIET
      restored hebt: nieuwe tunnel-tokens aanmaken (zie de app-repo's
      `deploy/README.md`).
- [ ] `/etc/hosts` op je MacBook, als Chrome/Safari de console niet laadt.

## 9. Eindverificatie

```bash
oc get application -n argocd
# alle 3 Synced + Healthy

oc get pods -A | grep -v Running
# leeg (op Completed jobs na)

curl -sk https://console-openshift-console.apps.sno.lab.vdzon.com | head -1
```

En handmatig: YouTrack, softwarefactory-dashboard en de news-feed openen via
hun publieke URLs, en de SMB-share zichtbaar op het thuisnetwerk.
