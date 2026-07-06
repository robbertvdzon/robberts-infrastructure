#!/usr/bin/env bash
#
# Cutover: schakel de 50-local-storage-mount MachineConfig over van
# by-id (specifiek voor de oude schijf) naar by-label/localpv (blijft werken
# na een volgende schijf-swap, zie ../../docs/disk-4tb-to-12tb-migration.md).
#
# Voorwaarde: 01-prepare-new-disk.sh en 02-migrate-data.sh zijn al gedraaid
# en de verificatie in 02 was schoon.
#
# MCO rebuildt de rendered config na deze apply en reboot de node — dat is
# een korte volledige downtime van het cluster, normaal voor SNO.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MC_FILE="$SCRIPT_DIR/../../manifests/machineconfigs/50-local-storage-mount.yaml"
NODE_HOST="${NODE_HOST:-192.168.178.64}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/okd-sno}"
LABEL="localpv"

ssh_node() { ssh -i "$SSH_KEY" -o ConnectTimeout=5 "core@$NODE_HOST" "$@"; }

if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  exit 1
fi

echo "[cutover] unmount tijdelijke /mnt/localpv-new"
ssh_node "sudo umount /mnt/localpv-new" || echo "       (al unmounted, prima)"

echo "[cutover] pas $MC_FILE aan: by-id -> by-label/$LABEL"
if grep -q "by-label/$LABEL" "$MC_FILE"; then
  echo "       al op by-label, niets te wijzigen"
else
  sed -i.bak -E "s#What=/dev/disk/by-id/[^ ]+#What=/dev/disk/by-label/$LABEL#" "$MC_FILE"
  rm -f "$MC_FILE.bak"
  echo "       gewijzigd:"
  grep "What=" "$MC_FILE"
fi

echo
echo "[cutover] oc apply $MC_FILE"
oc apply -f "$MC_FILE"

echo "[cutover] wachten op MCO rollout (node reboot, kan enkele minuten duren)..."
oc wait mcp/master --for=condition=Updated=True --timeout=600s

echo
echo "[cutover] verifieer:"
ssh_node "df -h /var/mnt/localpv"

echo
echo "[cutover] klaar. Zet workloads terug aan, bv.:"
echo "  oc scale deployment/samba-timemachine --replicas=1 -n smb-timemachine"
echo
echo "Vergeet niet: commit de gewijzigde $MC_FILE in git."
