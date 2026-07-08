# Vandaag: reinstall-rehearsal op een tijdelijke HDD

Eén lineaire checklist voor de complete oefening: backup → SSD wisselen voor
een tijdelijke HDD → OpenShift opnieuw installeren met scripts → verifiëren
dat alles weer werkt → oude SSD terug. Diepgaande uitleg/troubleshooting
staat in de andere docs in deze map — hier alleen de kortste route.

**Je originele SSD wordt niet aangeraakt.** Hij ligt aan de kant terwijl je
test; niks van wat hieronder gebeurt kan 'm beschadigen.

**Tijdens de test is de "echte" dashboard/news-feed niet bereikbaar**
(zelfde fysieke machine — DNS/router/Cloudflare wijzen naar hetzelfde IP,
dus je test-cluster beantwoordt tijdelijk dezelfde hostnamen). Dat is
verwacht en stopt zodra je de oude SSD terugzet.

**De externe USB-HDD (Time Machine-share)**: laat 'm gewoon aangesloten. De
install raakt alleen de interne OS-schijf aan; de externe HDD wordt alleen
gemount (via `51-external-hdd-mount`), nooit geformatteerd. Als je liever nul
risico wil voor de echte Time Machine-data erop: koppel 'm fysiek los vóór je
opstart — dan faalt alleen de mount-stap onschuldig (heeft `nofail`, blokkeert
de boot niet) en sla je de SMB-verificatie onderaan over.

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

USB in de PC, aanzetten, boot van USB — daarna niets te doen.
`install-to-disk.service` zit ingebakken in de ignition en wipet+installeert
de schijf helemaal zelf. Vanaf je MacBook meekijken (kan al meteen na het
booten, dit commando wacht zelf tot de API bereikbaar is):
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

**Alleen als de auto-install vastloopt** (zeldzaam op een tijdelijke schijf
zonder oude LVM): ssh naar de node
(`ssh-keygen -R 192.168.178.64 && ssh -i ~/.ssh/okd-sno core@192.168.178.64`),
dan `sudo wipefs -a /dev/sda` (bij een "busy partitions"-fout eerst
`sudo vgs` → `sudo vgchange -an <naam>` → opnieuw `wipefs`, zie
[install-troubleshooting.md](install-troubleshooting.md) Probleem 2).
`install-to-disk.service` pakt de wipe daarna binnen enkele seconden op.

## Fase 4 — Node-config, ArgoCD, apps

Eén blok, met precies één bewuste pauze (sealed-secrets-key restoren) erin:

```bash
cd ~/git/robberts-infrastructure
./scripts/machineconfig/apply-machineconfigs.sh   # mount externe HDD + DNS-fix, node reboot
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

Daarna de root-Application — de enige resource die nog imperatief moet
(sinds ArgoCD cluster-scoped draait, 2026-07-08, maakt hij namespaces én
ClusterRoles zelf aan uit git; er zijn géén handmatige namespace-applies
of losse RBAC-stappen meer, zie [architecture.md](architecture.md)):

```bash
./scripts/bootstrap/bootstrap-apps.sh
```

Agent-token + kubeconfig opnieuw genereren: zie
[access-and-credentials.md](access-and-credentials.md) — `SF_KUBECONFIG` in
`software-factory/secrets.env` blijft naar hetzelfde pad wijzen
(`~/okd-sno/sno/auth/kubeconfig-agent-readonly`), alleen de inhoud is nieuw.

## Fase 5 — Verifiëren

```bash
oc get application -n argocd
# verwacht: alle 5 Synced + Healthy (root-apps, personal-news-feed,
# softwarefactory-dashboard, smb-timemachine, agent-access)

oc get pods -A | grep -v Running
# verwacht: leeg (op Completed jobs na)
```

Handmatig: dashboard/news-feed openen via hun publieke URL's, en (als de
externe HDD aangesloten was) de SMB-share testen — zie
[smb-timemachine-test-procedure.md](smb-timemachine-test-procedure.md) stap 1
voor de snelle CLI-test.

## Fase 6 — Terug naar de originele SSD

- [ ] PC uitzetten
- [ ] Tijdelijke HDD eruit
- [ ] Originele SSD terug
- [ ] **Admin-credentials van het originele cluster terugzetten** —
      `build-okd-sno.sh` heeft in Fase 2 `~/okd-sno/sno/` weggegooid en
      opnieuw gegenereerd (`rm -rf sno/`), dus de kubeconfig/kubeadmin-
      password die daar nu staan horen bij het TEST-cluster, niet bij je
      originele. Zonder deze stap faalt `oc` hieronder met x509/auth-errors:
  ```bash
  cp ~/git/robberts-infrastructure/backups/<timestamp>/okd-sno/sno/auth/kubeconfig ~/okd-sno/sno/auth/kubeconfig
  cp ~/git/robberts-infrastructure/backups/<timestamp>/okd-sno/sno/auth/kubeadmin-password ~/okd-sno/sno/auth/kubeadmin-password
  ```
- [ ] SSH host-key van het test-cluster vergeten (zelfde IP, andere key):
  ```bash
  ssh-keygen -R 192.168.178.64
  ```
- [ ] Aanzetten, even wachten, `oc get co` — moet er precies zo uitzien als
      vóór vandaag (dit was nooit aangeraakt)

De tijdelijke HDD bevat na deze test dezelfde geheimen als productie
(sealed-secrets-key is gerestored, echte secrets zijn ontsleuteld op die
schijf). Behandel 'm dus niet als "leeg testmateriaal" — wis 'm
(`diskutil secureErase` oid.) als je 'm ergens anders voor gaat gebruiken.
