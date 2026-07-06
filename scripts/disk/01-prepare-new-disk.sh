#!/usr/bin/env bash
#
# Formatteer een nieuwe schijf met XFS + label "localpv" en mount 'm tijdelijk
# op /mnt/localpv-new, klaar voor de rsync in 02-migrate-data.sh.
#
# DESTRUCTIEF (mkfs). Vereist --yes als expliciete bevestiging.
#
# Gebruik (op de MacBook, script ssh't naar de node):
#   ./01-prepare-new-disk.sh /dev/sdc --yes

set -euo pipefail

NODE_HOST="${NODE_HOST:-192.168.178.64}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/okd-sno}"
LABEL="localpv"

if [[ $# -lt 2 || "${2:-}" != "--yes" ]]; then
  echo "Gebruik: $0 <device, bv. /dev/sdc> --yes" >&2
  echo "Dit formatteert het opgegeven device — vereist de expliciete --yes flag." >&2
  exit 1
fi

DEVICE="$1"

ssh_node() { ssh -i "$SSH_KEY" -o ConnectTimeout=5 "core@$NODE_HOST" "$@"; }

echo "[prepare] node: $NODE_HOST, device: $DEVICE"

echo "[prepare] check dat $DEVICE niet gemount is..."
if ssh_node "mount | grep -q '^$DEVICE '"; then
  echo "Error: $DEVICE is al gemount — verkeerde disk? Afgebroken." >&2
  exit 1
fi

echo "[prepare] huidige lsblk (controleer dat dit echt de nieuwe lege schijf is):"
ssh_node "lsblk -o NAME,SIZE,MODEL,SERIAL,MOUNTPOINTS"
echo
read -r -p "Zeker weten dat $DEVICE de NIEUWE (lege) schijf is? Typ 'ja': " confirm
if [[ "$confirm" != "ja" ]]; then
  echo "Afgebroken."
  exit 1
fi

echo "[prepare] mkfs.xfs -L $LABEL $DEVICE"
ssh_node "sudo mkfs.xfs -L $LABEL -f '$DEVICE'"

echo "[prepare] mount op /mnt/localpv-new"
ssh_node "sudo mkdir -p /mnt/localpv-new && sudo mount /dev/disk/by-label/$LABEL /mnt/localpv-new"

ssh_node "df -h /mnt/localpv-new"
echo
echo "[prepare] klaar. Volgende stap: 02-migrate-data.sh"
