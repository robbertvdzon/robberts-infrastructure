# Toegang & credentials

Twee niveaus. Alles wat automatisch draait (Claude Code, tester/refiner-
agent-containers, de Telegram-assistent) gebruikt het lage niveau. Het hoge
niveau is voor Robbert zelf, met de hand, alleen bij install of ArgoCD-
bootstrap.

## Niveau 1: break-glass admin (1Password, alleen handmatig)

**Credential**: de `kubeadmin`-wachtwoord / het `system:admin`-kubeconfig dat
de OpenShift-installer genereert (`~/okd-sno/sno/auth/kubeconfig` en
`kubeadmin-password`). Niets om "op te zetten" — dit bestaat al na elke
install, alleen de discipline eromheen is nieuw:

- **Nooit** in een repo's `secrets.env` of als default `KUBECONFIG` van een
  terminal-sessie.
- Zet de inhoud van `kubeadmin-password` (en eventueel het hele
  `kubeconfig`-bestand als bijlage) in **1Password** na elke install of
  credential-rotatie. Zie onderaan voor de huidige waarden om over te typen.
- Gebruik alleen voor:
  1. **Initiële cluster-install** (kubeadmin ontstaat automatisch bij de
     install, niets te doen behalve backuppen).
  2. **ArgoCD/Sealed-Secrets/storage (her)bootstrappen** — `deploy/bootstrap.sh`
     in `personal-news-feed-by-claude-code`, en
     `scripts/machineconfig/apply-machineconfigs.sh` in deze repo. Dit kán
     niet met minder rechten: OLM-operators installeren, SCC's toekennen en
     ConfigMaps van system-namespaces patchen is inherent cluster-admin-werk
     (en ArgoCD kan zichzelf niet installeren — chicken-and-egg).

Na zo'n sessie: `export KUBECONFIG=...` weer uitzetten / nieuwe shell openen
zodat je niet per ongeluk verder werkt met het admin-account.

## Niveau 2: `claude-agent` (read-only + 1 bewuste uitzondering)

**Credential**: ServiceAccount `claude-agent` in namespace `agent-access`
(manifests in [`../manifests/agent-access/`](../manifests/agent-access/)),
gebonden aan:

- de ingebouwde ClusterRole **`view`** (get/list/watch op zo goed als alles,
  **expliciet geen Secrets** — dat is een bewuste Kubernetes-designkeuze,
  niet iets wat wij hebben aangepast)
- een kleine aanvullende ClusterRole `agent-extra-view` (MachineConfig,
  MachineConfigPool, ClusterOperator, ArgoCD Applications/ApplicationSets —
  dingen die niet gegarandeerd aggregeren naar `view`)
- **`agent-preview-cleanup`**: de ENE bewuste uitzondering — `delete` op
  `projects`/`namespaces`, cluster-breed. Nodig omdat
  `OcPreviewEnvironmentCleaner.kt` (software-factory) automatisch
  `oc delete project <pnf-pr-N>` draait zodra een preview-PR sluit (ArgoCD's
  eigen prune ruimt de Application-resources op, niet de namespace zelf).
  RBAC kan niet op naam-patroon filteren, dus dit account kán in theorie
  **elke** namespace verwijderen — geaccepteerd risico, expliciet gekozen
  boven een aparte credential per code-pad of het herontwerpen van de
  preview-cleanup-flow (zie de opties die overwogen zijn: los een aparte
  credential, of ArgoCD de namespace zelf laten prunen).

**Verificatie** (uitgevoerd 2026-07-06):
```
✓ oc get pods -A                          → werkt
✓ oc get machineconfig                    → werkt
✓ oc get applications -n argocd           → werkt
✗ oc get secrets -n software-factory      → Forbidden
✗ oc create configmap ...                 → Forbidden
✗ oc scale deployment/...                 → Forbidden
✓ oc auth can-i delete projects           → yes (de bewuste uitzondering)
✗ oc auth can-i delete pods               → no
```

**Waar gebruikt**: `SF_KUBECONFIG` in `software-factory/secrets.env` wijst nu
naar `~/okd-sno/sno/auth/kubeconfig-agent-readonly` (was: het admin-
kubeconfig). Dit is wat Claude Code, de tester/refiner-agent-containers
(`DockerAgentRuntime.kt`) en de Telegram-assistent gemount krijgen.

**Rotatie**: het token verloopt niet (legacy SA-token-secret, bewust — dit is
een langlevende tool-credential). Bij lek/rotatie: verwijder
`agent-access/claude-agent-token` Secret + `oc apply -k manifests/agent-access/`
opnieuw (nieuwe token), en herbouw het kubeconfig-bestand (zie het script
hieronder). Dit hoeft NIET gebackupt te worden zoals de sealed-secrets-key —
het is zo opnieuw te genereren, geen dataverlies bij kwijtraken.

## Het `kubeconfig-agent-readonly`-bestand (opnieuw) genereren

Dit bestand is géén install-artefact — het is een handmatig samengesteld
kubeconfig dat het `claude-agent`-SA-token + cluster-CA bundelt. Het staat op
`~/okd-sno/sno/auth/kubeconfig-agent-readonly` (een **bestand**, niet een map —
`SF_KUBECONFIG` in `software-factory/secrets.env` wijst precies hiernaar, en de
software-factory mount dit als enkel bestand in de agent-container; een
verkeerd/ontbrekend pad wordt door Docker een lege map → `oc` in de container
kapot).

Vereist: ingelogd met het **admin**-account (`~/okd-sno/sno/auth/kubeconfig`)
én `oc apply -k manifests/agent-access/` al gedraaid (SA + token-Secret bestaan).

```bash
export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig   # admin
SA_NS=agent-access
SECRET=claude-agent-token
OUT=~/okd-sno/sno/auth/kubeconfig-agent-readonly

SERVER=$(oc whoami --show-server)                 # https://api.sno.lab.vdzon.com:6443
TOKEN=$(oc get secret "$SECRET" -n "$SA_NS" -o jsonpath='{.data.token}' | base64 -d)
oc get secret "$SECRET" -n "$SA_NS" -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/agent-ca.crt

rm -f "$OUT"
oc config set-cluster sno --server="$SERVER" \
   --certificate-authority=/tmp/agent-ca.crt --embed-certs=true --kubeconfig="$OUT"
oc config set-credentials claude-agent --token="$TOKEN" --kubeconfig="$OUT"
oc config set-context claude-agent --cluster=sno --user=claude-agent \
   --namespace=default --kubeconfig="$OUT"
oc config use-context claude-agent --kubeconfig="$OUT"
rm -f /tmp/agent-ca.crt
```

Verifieer (moet exact dit geven):
```bash
KUBECONFIG=~/okd-sno/sno/auth/kubeconfig-agent-readonly oc whoami
# system:serviceaccount:agent-access:claude-agent
oc auth can-i delete projects   --kubeconfig=$OUT   # yes  (de bewuste uitzondering)
oc auth can-i get secrets -n software-factory --kubeconfig=$OUT   # no
```

## Bij een reinstall

1. Na stap 3 van [disaster-recovery-playbook.md](disaster-recovery-playbook.md)
   (ArgoCD/Sealed-Secrets/storage-bootstrap, met het **admin**-account):
   ```bash
   oc apply -k manifests/agent-access/
   ```
2. Het `kubeconfig-agent-readonly`-bestand opnieuw genereren met het recept
   hierboven (100% herhaalbaar vanuit de manifests; het `build-okd-sno.sh`
   genereert dit bestand NIET, dat moet je zelf doen).
3. `SF_KUBECONFIG` in `software-factory/secrets.env` blijft hetzelfde pad
   wijzen (`~/okd-sno/sno/auth/kubeconfig-agent-readonly`) — alleen de
   inhoud van dat bestand is nieuw na een reinstall.
