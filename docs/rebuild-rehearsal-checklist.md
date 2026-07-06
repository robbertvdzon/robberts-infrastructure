# Vandaag: reinstall-rehearsal op een tijdelijke HDD

Eén lineaire checklist voor de complete oefening: backup → SSD wisselen voor
een tijdelijke HDD → OpenShift opnieuw installeren met scripts → verifiëren
dat alles weer werkt → oude SSD terug. Diepgaande uitleg/troubleshooting
staat in de andere docs in deze map — hier alleen de kortste route.

**Je originele SSD wordt niet aangeraakt.** Hij ligt aan de kant terwijl je
test; niks van wat hieronder gebeurt kan 'm beschadigen.

**Tijdens de test is de "echte" YouTrack/dashboard/news-feed niet bereikbaar**
(zelfde fysieke machine — DNS/router/Cloudflare wijzen naar hetzelfde IP,
dus je test-cluster beantwoordt tijdelijk dezelfde hostnamen). Dat is
verwacht en stopt zodra je de oude SSD terugzet.

**De 4TB-schijf (`/dev/sdb`)**: laat 'm gewoon aangesloten. De install raakt
alleen `/dev/sda` (de SSD/HDD) aan; `/dev/sdb` wordt alleen gemount, nooit
geformatteerd. Als je liever nul risico wil voor de echte Time Machine-data
erop: koppel 'm fysiek los vóór je opstart — dan faalt alleen de
`50-local-storage-mount`-stap onschuldig en sla je de SMB-verificatie
onderaan over.

---

## Fase 0 — Backup (vóór je iets loskoppelt)

```bash
cd ~/git/robberts-infrastructure
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig
./scripts/backup/backup-all.sh
```

Onthoud het pad dat het script print (`backups/<timestamp>/`) — daar staat
o.a. de sealed-secrets-key die je zo meteen terugzet. Hoeft voor een
same-day-test niet per se naar een andere locatie gekopieerd te worden, maar
doe het toch even (encrypted USB / 1Password) — kost een minuut.

## Fase 1 — Fysieke wissel

- [ ] PC uitzetten
- [ ] Huidige SSD (`/dev/sda`, 240GB) eruit, opzij leggen
- [ ] Tijdelijke HDD erin (zelfde SATA-poort/kabel; capaciteit ≥ 120GB)
- [ ] Monitor + toetsenbord aangesloten laten (nodig om de hostname te
      controleren vóór je via SSH verdergaat)

## Fase 2 — USB-stick maken

Ontbreken `openshift-install`/`oc`/`scos-live.iso`/`pull-secret.txt` in
`~/okd-sno` (bv. omdat je die net hebt opgeruimd)? Zie
[download-install-tools.md](download-install-tools.md) eerst.

```bash
~/git/robberts-infrastructure/scripts/install/build-okd-sno.sh
```

(Het script cd't zelf naar `~/okd-sno` — daar staan de grote binaries/ISO/
secrets die niet in git horen, zie [architecture.md](architecture.md).)
Dit hergenereert `sno/` en bakt een verse `scos-live.iso` met alle
install-fixes erin (zie [install-troubleshooting.md](install-troubleshooting.md)
als je nieuwsgierig bent wélke). Daarna flashen:

```bash
cd ~/okd-sno
diskutil list external          # zoek je USB-stick, bv. /dev/disk4
diskutil unmountDisk /dev/disk4
sudo dd if=scos-live.iso of=/dev/rdisk4 bs=1m status=progress
diskutil eject /dev/disk4
```

## Fase 3 — Installeren

USB in de PC, aanzetten, boot van USB. Wacht op het login-prompt en
controleer op het scherm: hostname moet `sno.lab.vdzon.com` zijn (bewijs dat
de ignition-fixes actief zijn, niet `localhost.localdomain`).

```bash
ssh-keygen -R 192.168.178.64
ssh -i ~/.ssh/okd-sno core@192.168.178.64
```

Op de tijdelijke HDD staat vrijwel zeker geen oude LVM, dus normaal gesproken
volstaat:
```bash
sudo wipefs -a /dev/sda
```
(Alleen als dat een foutmelding geeft over "busy partitions": eerst
`sudo vgs` om een volume-group-naam te vinden, dan
`sudo vgchange -an <naam>` en daarna opnieuw `wipefs`. Zie
[install-troubleshooting.md](install-troubleshooting.md) Probleem 2.)

`install-to-disk.service` pakt dit binnen enkele seconden op. Wacht op de
auto-reboot-melding en haal **direct** de USB-stick eruit.

Vanaf je MacBook meekijken:
```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig
./openshift-install --dir=sno wait-for install-complete --log-level=info
```
`connection refused` in de eerste 10-15 min is normaal. Eindigt met
"Install complete!". Verifieer:
```bash
oc get nodes
oc get co
```

## Fase 4 — Node-config, ArgoCD, apps

Eén blok, met precies één bewuste pauze (sealed-secrets-key restoren) erin:

```bash
cd ~/git/robberts-infrastructure
./scripts/machineconfig/apply-machineconfigs.sh   # mount 4TB-schijf + DNS-fix, node reboot
oc get mcp master -w                              # wacht tot UPDATED=True, dan Ctrl-C
```

```bash
./scripts/bootstrap/bootstrap-cluster.sh           # ArgoCD, Sealed Secrets, storage, Reflector — cluster-breed
```

**Zodra je "[3/7] Sealed Secrets controller" voorbij ziet komen** (of gewoon
nadat het script helemaal klaar is — maakt niet uit, hieronder werkt sowieso):

```bash
./scripts/backup/restore-sealed-secrets-key.sh backups/<timestamp>/sealed-secrets-keys.yaml
./scripts/bootstrap/bootstrap-cluster.sh           # nogmaals — idempotent, maakt de rest af
```

Daarna de app-specifieke bootstrap van personal-news-feed (checkt zelf of
het cluster-brede deel hierboven al staat):

```bash
cd ~/git/personal-news-feed-by-claude-code
./deploy/bootstrap.sh
```

Overige 3 Applications:
```bash
oc apply -f manifests/youtrack/argocd-application.yaml
oc apply -f manifests/smb-timemachine/namespace.yaml
oc apply -f manifests/smb-timemachine/argocd-application.yaml

cd ~/git/softwarefactory
oc apply -n argocd -f deploy/argocd-application.yaml
```

Read-only agent-toegang (voor Claude Code/tester-agents/Telegram-assistent):
```bash
oc apply -k manifests/agent-access/
```
Token + kubeconfig opnieuw genereren: zie
[access-and-credentials.md](access-and-credentials.md) — `SF_KUBECONFIG` in
`software-factory/secrets.env` blijft naar hetzelfde pad wijzen
(`~/okd-sno/sno/auth/kubeconfig-agent-readonly`), alleen de inhoud is nieuw.

## Fase 5 — Verifiëren

```bash
oc get application -n argocd
# verwacht: alle 4 Synced + Healthy (personal-news-feed, youtrack,
# softwarefactory-dashboard, smb-timemachine)

oc get pods -A | grep -v Running
# verwacht: leeg (op Completed jobs na)
```

Handmatig: YouTrack/dashboard/news-feed openen via hun publieke URL's, en
(als `/dev/sdb` aangesloten was) de SMB-share testen — zie
[smb-timemachine-test-procedure.md](smb-timemachine-test-procedure.md) stap 1
voor de snelle CLI-test.

## Fase 6 — Terug naar de originele SSD

- [ ] PC uitzetten
- [ ] Tijdelijke HDD eruit
- [ ] Originele SSD terug
- [ ] Aanzetten, even wachten, `oc get co` — moet er precies zo uitzien als
      vóór vandaag (dit was nooit aangeraakt)

De tijdelijke HDD bevat na deze test dezelfde geheimen als productie
(sealed-secrets-key is gerestored, echte secrets zijn ontsleuteld op die
schijf). Behandel 'm dus niet als "leeg testmateriaal" — wis 'm
(`diskutil secureErase` oid.) als je 'm ergens anders voor gaat gebruiken.
