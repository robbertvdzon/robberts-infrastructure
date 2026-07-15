# robberts-infrastructure

Alles wat nodig is om de thuis-OpenShift-server (SNO, `sno.lab.vdzon.com`) opnieuw
op te bouwen zodat hij **exact** weer werkt zoals nu — plus het onderhoud daarna
(disk-swap, backups).

Doel: uiteindelijk staat **alle** infra hier, ook app-specifieke deploy-
manifesten (niet alleen de cluster-brede lijmlaag). SMB/Time-Machine is
daarvan een voorbeeld (`manifests/smb-timemachine/`) — volledig statisch,
dus zonder complicaties te verplaatsen. `personal-news-feed-by-claude-code/deploy` en
`software-factory/deploy` blijven voorlopig staan waar ze staan: hun CI
bumpt image-tags in dezelfde commit als de build, en personal-news-feed's
PR-previews zijn gekoppeld aan per-PR-branch-manifesten in dat repo —
verhuizen kan, maar vereist een cross-repo GitHub-token voor CI en (voor
personal-news-feed) een herontwerp van het preview-mechanisme. Zie
[docs/architecture.md](docs/architecture.md) voor de volledige afweging.

## Structuur

```
docs/
  architecture.md                  — hoe alles in elkaar zit (hardware, netwerk, repo's, GitOps-flow)
  access-and-credentials.md         — het admin- vs read-only-credential-model
  disaster-recovery-playbook.md     — DE playbook: cluster van scratch opnieuw opbouwen
  cluster-inventory.md              — wat staat er nu op de cluster, is het nodig, is het reinstall-proof
  install-troubleshooting.md        — bekende install-valkuilen (6 pogingen/~18u ervaring), symptoom→fix
  backup-and-restore.md             — wat je moet backuppen vóór je iets riskants doet, en hoe
  download-install-tools.md         — openshift-install/oc/ISO opnieuw downloaden + pull-secret in 1Password
  smb-timemachine-usage.md          — permanente mount, Time Machine, andere backups, schijf vervangen
  manual-external-steps.md          — dingen die NIET in een script zitten (DNS, Cloudflare, router)

manifests/
  machineconfigs/                   — de 4 node-level configs die nu alleen los op het cluster stonden
  cluster-bootstrap/                — ArgoCD-operator-Subscription + ArgoCD CR (cluster-breed, verhuisd uit personal-news-feed)
  root-app/                         — app-of-apps: 1 root-Application beheert de 3 app-Applications (2026-07-08)
  smb-timemachine/                  — Samba-share op de externe USB-HDD voor Time Machine-backups (getest, werkend)
  agent-access/                     — read-only ServiceAccount voor Claude Code/agents/assistent

scripts/
  install/                          — build-okd-sno.sh (het ISO-buildscript — verhuisd hierheen, was alleen lokaal)
  bootstrap/                        — bootstrap-cluster.sh (ArgoCD/Sealed Secrets/storage/Reflector — verhuisd uit personal-news-feed)
  backup/                           — backup-all.sh + restore-sealed-secrets-key.sh
  machineconfig/                    — apply-machineconfigs.sh
  disk/                             — 4TB → 12TB migratiescripts
```

## Snel starten

- **Cluster opnieuw opbouwen (volledig, met alle uitleg)?** Begin bij [docs/disaster-recovery-playbook.md](docs/disaster-recovery-playbook.md).
- **Eerst backuppen?** Altijd — zie [docs/backup-and-restore.md](docs/backup-and-restore.md), en run
  `./scripts/backup/backup-all.sh` vóórdat je wat dan ook riskants doet.
- **Schijf vervangen?** Zie [docs/disk-4tb-to-12tb-migration.md](docs/disk-4tb-to-12tb-migration.md).

## Aanverwante repo's

| Repo | Rol |
|---|---|
| [`personal-news-feed-by-claude-code`](https://github.com/robbertvdzon/personal-news-feed-by-claude-code) | Eigen `deploy/bootstrap.sh` — alleen nog het app-specifieke deel (namespace, secrets, Application); het cluster-brede deel staat sinds 2026-07-07 in `scripts/bootstrap/bootstrap-cluster.sh` hierboven |
| [`software-factory`](https://github.com/robbertvdzon/software-factory) | softwarefactory-dashboard, eigen `deploy/argocd-application.yaml` (eenmalig `oc apply`, geen eigen bootstrap-script). YouTrack is verwijderd (2026-07-08) — de Software Factory gebruikt sinds de Postgres-tracker-migratie geen YouTrack meer. |

## Belangrijkste gotcha

Deze repo bevat **geen** private keys, kubeconfigs of plaintext secrets. Alle
backup-scripts schrijven naar `backups/` (gitignored) — kopieer die zelf naar
een encrypted USB-stick of 1Password. Zie [docs/backup-and-restore.md](docs/backup-and-restore.md).
