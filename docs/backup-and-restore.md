# Backup & restore

Run **altijd** `./scripts/backup/backup-all.sh` vóórdat je iets riskants doet
(reinstall, disk-swap, MachineConfig-experimenten). Het script is read-only
richting de cluster — het exporteert alleen, het wijzigt niets.

## Wat wordt gebackupt en waarom

| Item | Bron | Waarom kritiek |
|---|---|---|
| Sealed-secrets private key(s) | `kube-system` secret met label `sealedsecrets.bitnami.com/sealed-secrets-key` | **Zonder deze key zijn alle SealedSecrets in git (dashboard-secrets, newsfeed-api-keys) na een reinstall permanent onleesbaar.** Er was tot nu toe geen backup van. |
| Admin-kubeconfig + kubeadmin-password | `~/okd-sno/sno/auth/` | Toegang tot het huidige cluster (nutteloos na reinstall, wel nodig als de reinstall mislukt en je terug wil naar troubleshooten) |
| install-config.yaml, pull-secret.txt | `~/okd-sno/` | Nodig om exact dezelfde cluster-config opnieuw te installeren |
| `build-okd-sno.sh` | zit al in **deze repo** (`scripts/install/build-okd-sno.sh`), dus geen losse backup meer nodig | ISO-buildscript met de IPv6/ignition-workarounds — zonder dit script moet je alle install-quirks uit `install-troubleshooting.md` met de hand reproduceren |
| SSH private key | `~/.ssh/okd-sno` | Toegang tot de node zelf |
| Live MachineConfigs (diff-check) | cluster, `50-local-storage-mount` + `99-master-strip-bad-search-domain` | Vangnet: als de live config ooit afwijkt van wat in `manifests/machineconfigs/` staat, zie je dat in de backup-diff |
| `secrets.env` / `secrets-cluster.env` | `software-factory/`, `personal-news-feed-by-claude-code/deploy/` | Plaintext bron voor alle SealedSecrets — gitignored in de app-repo's, dus alleen lokaal aanwezig. Nodig om na een reinstall (met een NIEUWE sealed-secrets key, want je restored 'm niet) alles opnieuw te resealen. |

## Waar de backup terechtkomt

`backups/<datum-tijd>/` in deze repo — staat in `.gitignore`, wordt dus nooit
gecommit. **Kopieer deze map na elke run naar iets buiten deze laptop**
(encrypted USB-stick, 1Password (als bijlage), externe schijf). Als de laptop
crasht en dit is de enige kopie, heb je niets aan de backup.

## Restore-volgorde bij een reinstall

Zie het volledige playbook in [disaster-recovery-playbook.md](disaster-recovery-playbook.md).
Kort samengevat, de sealed-secrets key moet je restoren **direct nadat** de
Sealed Secrets controller net geïnstalleerd is (stap 3 van
`personal-news-feed-by-claude-code/deploy/bootstrap.sh`) en **voordat** je
verder gaat — anders genereert de controller een nieuwe key en ben je alsnog
te laat:

```bash
./scripts/backup/restore-sealed-secrets-key.sh backups/<datum-tijd>/sealed-secrets-keys.yaml
```

## Als je de sealed-secrets key NIET restored (bewust, of te laat)

Dan werken de bestaande `SealedSecret`-resources in git niet meer. Je moet
per app:

1. `secrets.env` / `secrets-cluster.env` uit de backup terugzetten (of uit 1Password)
2. `./deploy/seal-secrets.sh` opnieuw draaien (gebruikt het NIEUWE cluster-cert)
3. De gegenereerde `sealed-secret-*.yaml` committen en pushen
4. ArgoCD laten syncen

Dit is precies wat er al staat gedocumenteerd in
`personal-news-feed-by-claude-code/deploy/README.md` en
`software-factory/deploy/README.md` — deze repo voegt alleen de
sealed-secrets-key-restore-route toe zodat je dat meestal kan overslaan.
