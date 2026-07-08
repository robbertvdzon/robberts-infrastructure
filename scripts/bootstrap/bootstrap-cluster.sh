#!/usr/bin/env bash
#
# Bootstrap voor een vers OpenShift-cluster — het generieke, cluster-brede
# deel. Idempotent (mag je opnieuw runnen).
#
# Verhuisd hierheen vanuit personal-news-feed-by-claude-code/deploy/bootstrap.sh
# (2026-07-07): dat script deed dit én PNF-specifieke dingen (namespace,
# preview-ns-labeller, de Application zelf) door elkaar. Dit hier is precies
# het deel waar het dashboard, de SMB-share én toekomstige apps allemaal op
# leunen — hoort dus in de "lijmlaag"-repo, niet in één app-repo.
#
#    1. argocd-operator subscriben via OperatorHub
#    2. ArgoCD CR apply'en (applicationSet enabled, server-route)
#    3. ArgoCD namespace-creator RBAC (ClusterRole+Binding, zodat
#       CreateNamespace=true in een Application ook echt werkt)
#    4. Sealed Secrets controller installeren
#    5. Cluster public-cert ophalen → manifests/cluster-bootstrap/cluster-cert.pem
#    6. Local-path-provisioner installeren + configureren voor OpenShift
#       (privileged helper-pod, path naar /var/lib, default StorageClass)
#    7. Reflector (Secret-mirror naar preview-namespaces)
#    8. ApplicationSet-controller verifiëren (idempotency-patch)
#
# Daarna PER APP nog een eigen (veel kortere) bootstrap-stap nodig:
# namespace aanmaken + labelen, app-specifieke secrets, de ArgoCD Application
# zelf. Zie bv. personal-news-feed-by-claude-code/deploy/bootstrap.sh, of voor
# dashboard/smb-timemachine gewoon `oc apply -f deploy/*-application.yaml`
# (zie ../../docs/disaster-recovery-playbook.md stap 4/6).
#
# Aannames:
#   - `oc` is geïnstalleerd en ingelogd op het juiste cluster (`oc whoami`).
#   - `kubeseal` is geïnstalleerd (brew install kubeseal).
#   - OperatorHub draait (standaard op OpenShift; op vanilla Kubernetes
#     moet je eerst OLM installeren).
#
# Run vanuit de repo-root:
#   ./scripts/bootstrap/bootstrap-cluster.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANIFEST_DIR="$REPO_ROOT/manifests/cluster-bootstrap"

ARGOCD_NS="argocd"
LOCAL_PATH_NS="local-path-storage"
LOCAL_PATH_SA="local-path-provisioner-service-account"
SEALED_SECRETS_VERSION="v0.27.0"
LOCAL_PATH_VERSION="v0.0.30"
REFLECTOR_VERSION="v10.0.42"
CERT_FILE="$MANIFEST_DIR/cluster-cert.pem"

# ─── pre-flight ───────────────────────────────────────────────────────
for cmd in oc kubeseal; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: $cmd niet gevonden in PATH." >&2
    exit 1
  fi
done

if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  echo "       Dit script heeft het break-glass admin-account nodig, zie" >&2
  echo "       ../../docs/access-and-credentials.md — niet de read-only agent-kubeconfig." >&2
  exit 1
fi

echo "[bootstrap] cluster: $(oc whoami --show-server)"
echo "[bootstrap] user:    $(oc whoami)"

# ─── 1. argocd-operator (OperatorHub subscription) ────────────────────
# Community-operator uit channel 'alpha'. installPlanApproval=Automatic
# laat 'm zichzelf upgraden binnen het channel. Op fresh clusters duurt
# de eerste install ~2 min (catalog-resolve + image-pull).
echo
echo "[1/8] argocd-operator subscription"
oc apply -f "$MANIFEST_DIR/argocd-operator-subscription.yaml"

echo "      wachten op argocd CRD (signal dat de operator klaar is)..."
elapsed=0
until oc get crd argocds.argoproj.io >/dev/null 2>&1; do
  sleep 5
  elapsed=$((elapsed + 5))
  if (( elapsed >= 300 )); then
    echo "Error: argocd CRD niet beschikbaar na 5 min." >&2
    echo "       Check: oc get csv -n openshift-operators | grep argocd" >&2
    exit 1
  fi
done
echo "      operator ready"

# ─── 2. ArgoCD CR ─────────────────────────────────────────────────────
# Minimale CR met ApplicationSet enabled en route. De operator creëert
# vervolgens argocd-server, repo-server, redis, application-controller en
# applicationset-controller.
echo
echo "[2/8] ArgoCD instance ($ARGOCD_NS)"
oc create namespace "$ARGOCD_NS" --dry-run=client -o yaml | oc apply -f -
oc apply -f "$MANIFEST_DIR/argocd-cr.yaml"
echo "      wachten op argocd-server..."
oc rollout status -n "$ARGOCD_NS" deploy/argocd-server --timeout=300s 2>/dev/null || \
  echo "      (warning: argocd-server niet ready binnen 5 min)"
oc rollout status -n "$ARGOCD_NS" deploy/argocd-applicationset-controller --timeout=180s 2>/dev/null || true

# ─── 3. ArgoCD namespace-creator RBAC ─────────────────────────────────
# De argocd-operator geeft de application-controller-ServiceAccount alleen
# per-namespace Role/RoleBindings (in namespaces die 'ie al beheert), nooit
# een cluster-brede ClusterRoleBinding — zonder dit kan `CreateNamespace=true`
# in een Application nooit werken (Namespace is cluster-scoped). Zie
# ../../manifests/cluster-bootstrap/argocd-namespace-creator-rbac.yaml voor
# de volledige uitleg. Bewust GEEN delete-recht.
echo
echo "[3/8] ArgoCD namespace-creator RBAC"
oc apply -f "$MANIFEST_DIR/argocd-namespace-creator-rbac.yaml"

# ─── 4. Sealed Secrets controller ─────────────────────────────────────
echo
echo "[4/8] Sealed Secrets controller ($SEALED_SECRETS_VERSION)"
oc apply -f "https://github.com/bitnami-labs/sealed-secrets/releases/download/${SEALED_SECRETS_VERSION}/controller.yaml"
oc rollout status -n kube-system deploy/sealed-secrets-controller --timeout=180s

# ─── 5. Cluster cert ophalen ──────────────────────────────────────────
# Op een vers cluster heeft de sealed-secrets controller een NIEUWE
# keypair. Bestaande SealedSecrets in de app-repo's, versleuteld met een
# OUDE keypair, kunnen dan niet ontsleuteld worden door dit nieuwe cluster.
#
# DR-opties als het cert wijzigt:
#   (a) Restore de oude master-key uit je backup:
#       ./scripts/backup/restore-sealed-secrets-key.sh <backup>/sealed-secrets-keys.yaml
#   (b) Re-encrypt per app (vereist secrets.env/secrets-cluster.env uit
#       1Password): ./deploy/seal-secrets.sh in de betreffende app-repo,
#       committen, ArgoCD laten syncen.
echo
echo "[5/8] Cluster public-cert ophalen → $CERT_FILE"
mkdir -p "$MANIFEST_DIR"
if [[ -f "$CERT_FILE" ]]; then
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  kubeseal --fetch-cert > "$tmp"
  if cmp -s "$tmp" "$CERT_FILE"; then
    echo "      cert is ongewijzigd."
  else
    mv "$tmp" "$CERT_FILE"
    echo "      ⚠️  cert is GEWIJZIGD — bestaande sealed secrets in de app-repo's werken"
    echo "      niet meer tenzij je de oude master-key restored (zie hierboven)."
  fi
else
  kubeseal --fetch-cert > "$CERT_FILE"
  echo "      cert opgehaald — commit $CERT_FILE!"
fi

# ─── 6. Local-path-provisioner (storage) ──────────────────────────────
# OpenShift's restricted SCC blokkeert hostPath, en RHCOS heeft SELinux
# enforcing — daarom moet de helper-pod privileged draaien. Daarnaast
# is /opt read-only op RHCOS, dus we routeren naar /var/lib.
echo
echo "[6/8] Local-path-provisioner ($LOCAL_PATH_VERSION)"

# Install
oc apply -f "https://raw.githubusercontent.com/rancher/local-path-provisioner/${LOCAL_PATH_VERSION}/deploy/local-path-storage.yaml"
oc rollout status -n "$LOCAL_PATH_NS" deploy/local-path-provisioner --timeout=120s

# Grant privileged SCC aan de provisioner-SA — nodig om de helper-pods
# als root + spc_t te kunnen draaien (anders SELinux denial op hostPath).
echo "      grant SCC privileged → $LOCAL_PATH_SA in $LOCAL_PATH_NS"
oc adm policy add-scc-to-user privileged -z "$LOCAL_PATH_SA" -n "$LOCAL_PATH_NS" >/dev/null

# ConfigMap patchen:
#   * config.json: path naar /var/lib/local-path-provisioner (RHCOS-veilig)
#   * helperPod.yaml: securityContext.privileged=true (SELinux + hostPath)
CONFIG_JSON='{
        "nodePathMap":[
        {
                "node":"DEFAULT_PATH_FOR_NON_LISTED_NODES",
                "paths":["/var/lib/local-path-provisioner"]
        }
        ]
}'

HELPER_POD_YAML='apiVersion: v1
kind: Pod
metadata:
  name: helper-pod
spec:
  priorityClassName: system-node-critical
  tolerations:
    - key: node.kubernetes.io/disk-pressure
      operator: Exists
      effect: NoSchedule
  containers:
  - name: helper-pod
    image: busybox
    imagePullPolicy: IfNotPresent
    securityContext:
      privileged: true
'

PATCH=$(python3 -c "
import sys, json
print(json.dumps({
  'data': {
    'config.json': '''$CONFIG_JSON''',
    'helperPod.yaml': '''$HELPER_POD_YAML'''
  }
}))
")
oc patch configmap -n "$LOCAL_PATH_NS" local-path-config --type merge -p "$PATCH" >/dev/null
echo "      ConfigMap gepatcht (path + privileged helper)"

# Maak local-path de default StorageClass
oc patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}' >/dev/null
echo "      local-path StorageClass is nu default"

# Restart provisioner om de ConfigMap-patches op te pakken
oc rollout restart -n "$LOCAL_PATH_NS" deploy/local-path-provisioner >/dev/null
oc rollout status  -n "$LOCAL_PATH_NS" deploy/local-path-provisioner --timeout=60s

# ─── 7. Reflector (Secret-mirror voor preview-namespaces) ─────────────
# Mirror't Secrets naar nieuwe pnf-*-preview-namespaces (gestuurd via
# annotations op de Secret zelf, zie personal-news-feed's newsfeed-api-keys).
# Zonder reflector zou elke preview-namespace een eigen SealedSecret nodig
# hebben.
echo
echo "[7/8] Reflector ($REFLECTOR_VERSION)"
oc apply -f "https://github.com/emberstack/kubernetes-reflector/releases/download/${REFLECTOR_VERSION}/reflector.yaml"
oc rollout status -n kube-system deploy/reflector --timeout=120s

# ─── 8. ApplicationSet-controller idempotency-check ───────────────────
# De ArgoCD CR (stap 2) zet `applicationSet: {}` al; deze patch is een
# safety net voor het geval iemand de CR handmatig gewijzigd heeft.
echo
echo "[8/8] Verify ApplicationSet-controller"
oc patch argocd argocd -n "$ARGOCD_NS" --type merge -p '{"spec":{"applicationSet":{}}}' >/dev/null
oc rollout status -n "$ARGOCD_NS" deploy/argocd-applicationset-controller --timeout=120s 2>/dev/null || true

echo
echo "[bootstrap-cluster] klaar. ArgoCD, Sealed Secrets, storage en Reflector staan."
echo "Volgende stap: app-specifieke namespace-prereqs, dan de root-Application:"
echo "  cd ~/git/personal-news-feed-by-claude-code && ./deploy/bootstrap.sh"
echo "  cd ~/git/robberts-infrastructure && oc apply -f manifests/smb-timemachine/namespace.yaml"
echo "  oc apply -f manifests/root-app/root-application.yaml   # beheert personal-news-feed, smb-timemachine, softwarefactory-dashboard"
