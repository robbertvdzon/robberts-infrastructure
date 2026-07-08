#!/usr/bin/env bash
#
# App-bootstrap: apply't de root-Application — de ENIGE resource die na
# bootstrap-cluster.sh nog imperatief aangemaakt moet worden. Al het andere
# (3 app-Applications, PR-preview-ApplicationSet, github-pr-token,
# preview-ns-labeller Deployment + RBAC, agent-access) sync't ArgoCD daarna
# zelf uit manifests/root-app/apps/. Idempotent.
#
# Historie: tot 2026-07-08 deed dit script (en z'n voorgangers in drie
# repo's) ook namespaces aanmaken + labelen en ClusterRole-RBAC applyen —
# nodig omdat de ArgoCD-instance in namespaced mode een namespace nooit
# voor het éérst zelf mocht aanmaken (allow-list-kip-en-ei, zie
# ../../docs/architecture.md). Sinds de instance cluster-scoped draait
# (ARGOCD_CLUSTER_CONFIG_NAMESPACES in ../../manifests/cluster-bootstrap/
# argocd-operator-subscription.yaml) doet CreateNamespace=true dat gewoon
# zelf en mag ArgoCD ook ClusterRoles/Namespaces uit git beheren.
#
# Vereist: bootstrap-cluster.sh al gedraaid én — bij een rebuild — de
# sealed-secrets-key al gerestored (restore-sealed-secrets-key.sh), anders
# komen de secrets niet uit de SealedSecrets.
#
# Run vanuit de repo-root:
#   ./scripts/bootstrap/bootstrap-apps.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ─── pre-flight ───────────────────────────────────────────────────────
if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  exit 1
fi

if ! oc get crd argocds.argoproj.io >/dev/null 2>&1; then
  echo "Error: ArgoCD CRD ontbreekt — eerst ./scripts/bootstrap/bootstrap-cluster.sh draaien." >&2
  exit 1
fi

if ! oc get deploy -n kube-system sealed-secrets-controller >/dev/null 2>&1; then
  echo "Error: sealed-secrets-controller ontbreekt — eerst bootstrap-cluster.sh draaien." >&2
  exit 1
fi

echo "[bootstrap-apps] cluster: $(oc whoami --show-server)"

echo
echo "[1/1] root-Application (app-of-apps)"
oc apply -f "$REPO_ROOT/manifests/root-app/root-application.yaml"

echo
echo "[bootstrap-apps] klaar. ArgoCD sync't nu alles zelf; volg met:"
echo "  oc get application -n argocd   # root-apps + 4 apps → Synced/Healthy"
echo
echo "Blijven Applications hangen op 'namespace ... is not managed'? Dan"
echo "draait de instance nog in namespaced mode — check dat de operator-"
echo "Subscription de env ARGOCD_CLUSTER_CONFIG_NAMESPACES=argocd heeft"
echo "(manifests/cluster-bootstrap/argocd-operator-subscription.yaml) en dat"
echo "de operator-pod herstart is na die wijziging."
echo
echo "Nog handmatig (alleen indien van toepassing):"
echo "  - agent-token/kubeconfig hergenereren: docs/access-and-credentials.md"
