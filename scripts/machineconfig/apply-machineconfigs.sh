#!/usr/bin/env bash
#
# Apply de node-level MachineConfigs die niet bij een specifieke app horen:
#   - 51-external-hdd-mount: mount de externe USB-HDD op /var/mnt/external-hdd
#     (Time Machine-bestemming; vervangt de voormalige 50-local-storage-mount)
#   - 99-master-strip-bad-search-domain: DNS ndots/search-domain fix (zie
#     ../../docs/architecture.md voor de root cause)
#   - 99-master-disable-ipv6 / 99-master-hostname: post-bootstrap vangnet
#     voor de fixes die primair in de ignition zitten (build-okd-sno.sh) —
#     zie ../../docs/install-troubleshooting.md Probleem 3 en 4. Op een
#     vers cluster (net geïnstalleerd met build-okd-sno.sh) bestaan deze al
#     vanaf de eerste boot; dit script is dan een no-op (identieke content).
#
# Idempotent. Elke wijziging laat de Machine Config Operator een nieuwe
# rendered-config bouwen en de node rebooten (bij een SNO-cluster = korte
# downtime van alles, dat is verwacht).
#
# Vereisten: oc ingelogd op het juiste cluster (oc whoami).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MC_DIR="$SCRIPT_DIR/../../manifests/machineconfigs"

if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  exit 1
fi

echo "[machineconfigs] cluster: $(oc whoami --show-server)"

for f in "$MC_DIR"/*.yaml; do
  name="$(basename "$f")"
  echo
  echo "[apply] $name"
  oc apply -f "$f"
done

echo
echo "[machineconfigs] klaar. MCO bouwt de rendered config; volg de voortgang met:"
echo "  oc get mcp master -w"
echo
echo "Een reboot van de node is normaal na een wijziging. Verifieer na de reboot:"
echo "  ssh -i ~/.ssh/okd-sno core@192.168.178.64 'df -h /var/mnt/localpv'"
echo "  ssh -i ~/.ssh/okd-sno core@192.168.178.64 'cat /etc/resolv.conf'  # geen lab.vdzon.com in search"
