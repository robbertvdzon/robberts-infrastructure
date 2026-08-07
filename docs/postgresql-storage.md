# PostgreSQL-opslag en herstel

Status: vastgesteld op 7 augustus 2026 voor HKH, HKH Autopilot en Product Factory.

## Besluit

- PostgreSQL is de enige datastore in deze fase; S3/objectstorage en LVM Storage vallen buiten
  scope.
- Iedere productiedatabase krijgt een eigen `ReadWriteOnce`-PVC via de bestaande `local-path`-
  storageclass. Live inventarisatie bevestigt dat deze provisioner onder
  `/var/lib/local-path-provisioner` op de XFS-SSD staat (circa 953GB, 839GB vrij tijdens de
  inventarisatie).
- De local-path-provisioner relabelt zijn hostPath-volumes niet voor OpenShift SELinux. Daarom
  gebruikt iedere database een eigen ServiceAccount met de beperkte `local-path-postgresql`-SCC.
  Deze SCC staat alleen PVC-volumes toe; privileged containers, host networking en privilege
  escalation blijven uitgeschakeld.
- Iedere HKH-pull-requestpreview krijgt een kleinere eigen PVC via dezelfde storageclass. De hele
  namespace, inclusief PVC en PV (`reclaimPolicy: Delete`), blijft disposable.
- Iedere productiedatabase maakt dagelijks een PostgreSQL custom-format dump met checksum naar
  `/var/mnt/external-hdd/postgres-backups/<applicatie>`. De externe 16TB-HDD is live als 15TB exFAT
  gemount en is geschikt voor dumpbestanden, maar niet voor de live PostgreSQL-datadirectory.
- Dumps worden dertig dagen bewaard. Een dump telt pas als bruikbaar nadat `pg_restore --list`
  slaagt; daarnaast wordt een echte restore naar een tijdelijke PostgreSQL-instantie uitgevoerd en
  functioneel gecontroleerd.

## Storingsmodel

- Een podrestart of nieuwe rollout behoudt de database via de PVC.
- Een fout in de node-OS-installatie kan via de dump op de afzonderlijke USB-HDD worden hersteld.
- De USB-HDD is op dezelfde fysieke locatie aangesloten en is dus geen bescherming tegen verlies
  van de volledige locatie of gelijktijdige schade aan beide apparaten.
- Wanneer de SSD-capaciteit later onvoldoende blijkt, volgt een nieuw besluit; deze fase bouwt geen
  voorbarige migratie naar LVM, een operator of externe PostgreSQL.

## Veilige migratie vanaf `emptyDir`

1. Maak vlak vóór de rollout een dump van de bestaande database.
2. Controleer de dump met `pg_restore --list` en bewaar een SHA-256-checksum.
3. Laat ArgoCD de PVC en de gewijzigde databaseworkload uitrollen.
4. Zet de dump terug voordat er nieuwe productiedata wordt geschreven.
5. Controleer Flyway, tabelaantallen, API-health en een functionele leesactie.
6. Start een handmatige backupjob en herstel de gemaakte HDD-dump naar een tijdelijke database.

Secrets blijven in de bestaande applicatie-Secrets. De backup-CronJob gebruikt per namespace een
eigen ServiceAccount met uitsluitend de beperkte `postgresql-host-backup`-SCC om de backupmap te
mounten; het account krijgt geen Kubernetes-API-rechten. De database-ServiceAccount krijgt deze
hostPath-SCC nadrukkelijk niet.
