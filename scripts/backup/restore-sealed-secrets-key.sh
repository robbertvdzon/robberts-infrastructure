#!/usr/bin/env bash
#
# Restore de sealed-secrets private key(s) op een VERS cluster, zodat bestaande
# SealedSecrets uit git (dashboard-secrets, newsfeed-api-keys, ...) meteen weer
# ontsleuteld kunnen worden — je hoeft dan niks opnieuw te resealen.
#
# Timing is kritiek: dit moet direct NA het installeren van de Sealed Secrets
# controller (stap 3 van personal-news-feed-by-claude-code/deploy/bootstrap.sh)
# en VOORDAT je de rest van dat bootstrap-script laat verdergaan. Zodra de
# controller draait zonder een bestaande key te vinden, genereert hij een
# NIEUWE key — en dan is deze restore te laat (dan moet je alsnog alles
# resealen, zie ../../docs/backup-and-restore.md).
#
# Gebruik:
#   ./restore-sealed-secrets-key.sh <pad-naar-backup>/sealed-secrets-keys.yaml

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Gebruik: $0 <pad-naar-backup>/sealed-secrets-keys.yaml" >&2
  exit 1
fi

KEY_FILE="$1"
if [[ ! -f "$KEY_FILE" ]]; then
  echo "Error: bestand niet gevonden: $KEY_FILE" >&2
  exit 1
fi

if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  exit 1
fi

echo "[restore] cluster: $(oc whoami --show-server)"
echo "[restore] apply $KEY_FILE naar kube-system"
oc apply -f "$KEY_FILE"

echo "[restore] herstart de sealed-secrets-controller zodat hij de restored key oppikt"
oc delete pod -n kube-system -l name=sealed-secrets-controller --ignore-not-found
oc rollout status -n kube-system deploy/sealed-secrets-controller --timeout=120s

echo
echo "[restore] klaar. Verifieer met:"
echo "  kubeseal --fetch-cert  # moet hetzelfde cert teruggeven als deploy/cluster-cert.pem in de app-repo's"
echo
echo "Als het cert AFWIJKT van deploy/cluster-cert.pem: er zijn meerdere keys"
echo "hersteld of de controller had al een key gegenereerd vóór deze restore."
echo "Check: oc get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key"
