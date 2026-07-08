# 4TB → 12TB schijf-migratie

**Achterhaald sinds 2026-07-08.** De interne 4TB-schijf is niet meer in gebruik — de Time
Machine-share draait nu op een externe USB-HDD (zie [architecture.md](architecture.md) en
[../manifests/smb-timemachine/README.md](../manifests/smb-timemachine/README.md)), en
`50-local-storage-mount` is verwijderd. Deze procedure is dus niet meer van toepassing; bewaard
als referentie voor het onderliggende MachineConfig/`by-label`-patroon, mocht een toekomstige
schijf-swap (van de externe HDD) ooit nodig zijn.

---

Huidige situatie (historisch, zie boven): `/dev/sdb` (4TB) gemount op `/var/mnt/localpv` via de
`50-local-storage-mount` MachineConfig, geadresseerd via
`/dev/disk/by-id/wwn-0x5000c500f15d6c9c` (zie [architecture.md](architecture.md)).
Dat `by-id` verandert per fysieke schijf — bij een swap moet je dus normaal de
MachineConfig aanpassen én de node laten rebooten (MCO-render-cyclus).

**Deze procedure schakelt tegelijk over op een `by-label`-mount.** Daarna is
een volgende schijf-swap alleen nog: nieuwe schijf formatteren met hetzelfde
label, data overzetten, oude schijf eruit — geen MachineConfig-wijziging of
reboot meer nodig.

## Voorwaarden

- De 12TB-schijf moet **tegelijk** met de 4TB-schijf aangesloten kunnen
  worden voor de copy-fase (rsync werkt lokaal veel sneller en betrouwbaarder
  dan over het netwerk). Op de ASUS PRIME H410M-K: check hoeveel vrije
  SATA-poorts/voeding-connectors er zijn. Geen vrije poort? Gebruik een USB3-
  behuizing voor de 12TB-schijf tijdens de copy-fase, en verplaats 'm daarna
  intern.
- `ssh` naar de node werkt (`~/.ssh/okd-sno`).
- Als er op dat moment een workload op `/var/mnt/localpv` schrijft (bv. de
  SMB/Time-Machine-share): die moet je tijdens de copy op 0 replicas zetten,
  anders mis je bestanden die tijdens de rsync bijgeschreven worden.

## Stappen

### 1. Nieuwe schijf voorbereiden (formatteren + label)

```bash
./scripts/disk/01-prepare-new-disk.sh /dev/sdc --yes
```

Dit:
- Verifieert dat `/dev/sdc` niet al gemount is (voorkomt per ongeluk de
  verkeerde schijf wipen)
- `mkfs.xfs -L localpv /dev/sdc`
- Mount 'm tijdelijk op `/mnt/localpv-new`

`--yes` is verplicht — zonder die flag doet het script niets (destructieve
`mkfs`, bewust een expliciete stap).

### 2. Workloads pauzeren die op de schijf schrijven

```bash
oc scale deployment/samba-timemachine --replicas=0 -n smb-timemachine
```

(Namespace/naam: zie `manifests/smb-timemachine/`.)

### 3. Data overzetten

```bash
./scripts/disk/02-migrate-data.sh
```

Dit doet `rsync -aHAX --numeric-ids --info=progress2` van
`/var/mnt/localpv` naar `/mnt/localpv-new`, gevolgd door een verificatiepas
(bestandscount + steekproef-checksums). Draai dit script **twee keer** als de
eerste run lang duurt — de tweede run is een incrementele rsync die alleen
verschillen oppakt (bv. bestanden die tijdens de eerste run nog geschreven
werden) en is meestal binnen enkele minuten klaar.

Verifieer expliciet voor je verder gaat:
```bash
diff <(ssh -i ~/.ssh/okd-sno core@192.168.178.64 'sudo find /var/mnt/localpv -type f | sort') \
     <(ssh -i ~/.ssh/okd-sno core@192.168.178.64 'sudo find /mnt/localpv-new -type f | sort')
# leeg output = zelfde bestandslijst
```

### 4. Cutover: MachineConfig omzetten naar by-label

```bash
./scripts/disk/03-cutover.sh
```

Dit:
1. Unmount `/mnt/localpv-new` (tijdelijke mount)
2. Past `manifests/machineconfigs/50-local-storage-mount.yaml` aan:
   `What=/dev/disk/by-id/wwn-...` → `What=/dev/disk/by-label/localpv`
3. `oc apply` die MachineConfig → MCO rebuildt, node reboot
4. Na de reboot: `/var/mnt/localpv` is nu de 12TB-schijf

Verifieer:
```bash
ssh -i ~/.ssh/okd-sno core@192.168.178.64 'df -h /var/mnt/localpv'
# Size ~12T
```

### 5. Workloads terug aanzetten

```bash
oc scale deployment/samba-timemachine --replicas=1 -n smb-timemachine
```

### 6. Oude 4TB-schijf verwijderen

Pas nadat je de nieuwe share een paar dagen hebt gebruikt en zeker weet dat
alles klopt (bv. een Time Machine-backup lukt): schroef de 4TB-schijf eruit.
Bewaar 'm nog even als koude backup voor het geval de rsync toch iets gemist
heeft.

## Volgende keer

Omdat de mount nu op `by-label/localpv` staat: een toekomstige schijf-swap is
gewoon stap 1–3 en 5–6 hierboven, zonder stap 4 (geen MachineConfig-wijziging,
geen reboot) — mits de nieuwe schijf hetzelfde label `localpv` krijgt.
