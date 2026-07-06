# robberts-infrastructure

Alles wat nodig is om de thuis-OpenShift-server (SNO, `sno.lab.vdzon.com`) opnieuw
op te bouwen zodat hij **exact** weer werkt zoals nu — plus het onderhoud daarna
(disk-swap, backups).

Deze repo bevat bewust **niet** de app-specifieke deploy-manifesten — die blijven
in de eigen repo van elke app (`personal-news-feed-by-claude-code/deploy`,
`softwarefactory/deploy`). Deze repo is de **lijmlaag**: alles wat op node-/
cluster-niveau zit en niet bij één specifieke app hoort, plus de documentatie die
de stappen uit al die repo's aan elkaar rijgt tot één playbook.

## Structuur

```
docs/
  architecture.md                  — hoe alles in elkaar zit (hardware, netwerk, repo's, GitOps-flow)
  access-and-credentials.md         — het admin- vs read-only-credential-model
  disaster-recovery-playbook.md     — DE playbook: cluster van scratch opnieuw opbouwen
  install-troubleshooting.md        — bekende install-valkuilen (6 pogingen/~18u ervaring), symptoom→fix
  backup-and-restore.md             — wat je moet backuppen vóór je iets riskants doet, en hoe
  disk-4tb-to-12tb-migration.md     — procedure om de 4TB-schijf te vervangen door 12TB
  smb-timemachine-test-procedure.md — hoe je de SMB/Time-Machine-share test
  manual-external-steps.md          — dingen die NIET in een script zitten (DNS, Cloudflare, router)

manifests/
  machineconfigs/                   — de 2 node-level configs die nu alleen los op het cluster stonden
  smb-timemachine/                  — Samba-share op de losse schijf voor Time Machine-backups (getest, werkend)
  agent-access/                     — read-only ServiceAccount voor Claude Code/agents/assistent

scripts/
  backup/                           — backup-all.sh + restore-sealed-secrets-key.sh
  machineconfig/                    — apply-machineconfigs.sh
  disk/                             — 4TB → 12TB migratiescripts
```

## Snel starten

- **Cluster opnieuw opbouwen?** Begin bij [docs/disaster-recovery-playbook.md](docs/disaster-recovery-playbook.md).
- **Eerst backuppen?** Altijd — zie [docs/backup-and-restore.md](docs/backup-and-restore.md), en run
  `./scripts/backup/backup-all.sh` vóórdat je wat dan ook riskants doet.
- **Schijf vervangen?** Zie [docs/disk-4tb-to-12tb-migration.md](docs/disk-4tb-to-12tb-migration.md).

## Aanverwante repo's

| Repo | Rol |
|---|---|
| [`personal-news-feed-by-claude-code`](https://github.com/robbertvdzon/personal-news-feed-by-claude-code) | Eigen `deploy/bootstrap.sh` installeert ArgoCD-operator, ArgoCD zelf, Sealed Secrets, local-path-provisioner, Reflector — de basis waar alle andere apps op leunen |
| [`software-factory`](https://github.com/robbertvdzon/software-factory) | YouTrack + softwarefactory-dashboard, eigen `deploy/*-application.yaml` (eenmalig `oc apply`, geen eigen bootstrap-script) |

## Belangrijkste gotcha

Deze repo bevat **geen** private keys, kubeconfigs of plaintext secrets. Alle
backup-scripts schrijven naar `backups/` (gitignored) — kopieer die zelf naar
een encrypted USB-stick of 1Password. Zie [docs/backup-and-restore.md](docs/backup-and-restore.md).
