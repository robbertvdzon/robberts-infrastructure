#!/bin/bash
# OKD SNO build script - klaar voor USB flash
# Robbert van Dale Zon, Mei 2026
#
# Verhuisd hierheen vanuit ~/build-okd-sno.sh (2026-07-06) — dat was de enige
# kopie, alleen lokaal, niet in git. Dit IS nu de canonieke versie.
#
# WORKDIR blijft bewust ~/okd-sno: daar staan de grote binaries (openshift-
# install, oc/kubectl, de ISO) en gevoelige bestanden (pull-secret.txt,
# sno/auth/kubeconfig) — die horen NIET in git (zie .gitignore in deze repo
# en ../../docs/backup-and-restore.md voor hoe ze wél gebackupt worden).
# Alleen het SCRIPT zelf hoort hier, in git, zodat het een reinstall
# overleeft.

set -e  # Stop bij errors

# ==== CONFIG ====
WORKDIR="$HOME/okd-sno"
CLUSTER_NAME="sno"
BASE_DOMAIN="lab.vdzon.com"
NODE_IP="192.168.178.64"
MACHINE_CIDR="192.168.178.0/24"
INSTALLATION_DISK="/dev/sda"
HOSTNAME="${CLUSTER_NAME}.${BASE_DOMAIN}"
SSH_KEY_PATH="$HOME/.ssh/okd-sno"

# ==== VALIDATIE ====
echo "🔍 Validating prerequisites..."

if [ ! -f "$WORKDIR/openshift-install" ]; then
  echo "❌ openshift-install not found at $WORKDIR/openshift-install"
  exit 1
fi

if [ ! -f "$WORKDIR/pull-secret.txt" ]; then
  echo "❌ pull-secret.txt not found at $WORKDIR/pull-secret.txt"
  exit 1
fi

if [ ! -f "$WORKDIR/scos-live.iso" ]; then
  echo "❌ scos-live.iso not found at $WORKDIR/scos-live.iso"
  exit 1
fi

if [ ! -f "$SSH_KEY_PATH.pub" ]; then
  echo "🔑 SSH key not found, generating..."
  ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -C "okd-sno"
fi

if ! command -v jq &> /dev/null; then
  echo "❌ jq is required. Install with: brew install jq"
  exit 1
fi

if ! command -v docker &> /dev/null; then
  echo "❌ docker is required and must be running"
  exit 1
fi

cd "$WORKDIR"

# ==== CLEANUP ====
echo "🧹 Cleaning up old install artifacts..."
rm -rf sno/
rm -f install-config.yaml install-config.yaml.bak

# ==== INSTALL-CONFIG ====
echo "📝 Creating install-config.yaml..."
SSH_KEY=$(cat "$SSH_KEY_PATH.pub")
PULL_SECRET=$(cat pull-secret.txt | jq -c .)

cat > install-config.yaml <<EOF
apiVersion: v1
baseDomain: $BASE_DOMAIN
metadata:
  name: $CLUSTER_NAME
compute:
- name: worker
  replicas: 0
controlPlane:
  name: master
  replicas: 1
networking:
  clusterNetwork:
  - cidr: 10.128.0.0/14
    hostPrefix: 23
  machineNetwork:
  - cidr: $MACHINE_CIDR
  networkType: OVNKubernetes
  serviceNetwork:
  - 172.30.0.0/16
platform:
  none: {}
bootstrapInPlace:
  installationDisk: $INSTALLATION_DISK
pullSecret: '$PULL_SECRET'
sshKey: |
  $SSH_KEY
EOF

cp install-config.yaml install-config.yaml.bak

# ==== MANIFESTS ====
echo "📦 Generating manifests..."
mkdir -p sno
cp install-config.yaml sno/install-config.yaml
./openshift-install --dir=sno create manifests

# ==== MACHINECONFIG: DISABLE IPV6 VIA NETWORKMANAGER ====
echo "🔧 Adding MachineConfig: disable IPv6 via NetworkManager..."

# Base64 encode de NetworkManager dispatcher script die IPv6 sysctls zet
NM_DISPATCHER_B64=$(echo '#!/bin/bash
# Disable IPv6 on all interfaces when they come up
INTERFACE="$1"
ACTION="$2"

if [ "$ACTION" = "up" ] || [ "$ACTION" = "pre-up" ]; then
  sysctl -w net.ipv6.conf.all.disable_ipv6=1 > /dev/null
  sysctl -w net.ipv6.conf.default.disable_ipv6=1 > /dev/null
  sysctl -w net.ipv6.conf."$INTERFACE".disable_ipv6=1 > /dev/null
fi
' | base64 | tr -d '\n')

# Base64 encode sysctl config voor boot-time disable
SYSCTL_CONF_B64=$(echo 'net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1
' | base64 | tr -d '\n')

cat > sno/openshift/99-master-disable-ipv6.yaml <<EOF
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  labels:
    machineconfiguration.openshift.io/role: master
  name: 99-master-disable-ipv6
spec:
  config:
    ignition:
      version: 3.2.0
    storage:
      files:
        - path: /etc/sysctl.d/95-disable-ipv6.conf
          mode: 0644
          overwrite: true
          contents:
            source: data:text/plain;charset=utf-8;base64,${SYSCTL_CONF_B64}
        - path: /etc/NetworkManager/dispatcher.d/95-disable-ipv6
          mode: 0755
          overwrite: true
          contents:
            source: data:text/plain;charset=utf-8;base64,${NM_DISPATCHER_B64}
EOF

# ==== MACHINECONFIG: HOSTNAME ====
echo "🏷️  Adding MachineConfig: hostname..."

HOSTNAME_B64=$(echo "$HOSTNAME" | base64 | tr -d '\n')

cat > sno/openshift/99-master-hostname.yaml <<EOF
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  labels:
    machineconfiguration.openshift.io/role: master
  name: 99-master-hostname
spec:
  config:
    ignition:
      version: 3.2.0
    storage:
      files:
        - path: /etc/hostname
          mode: 0644
          overwrite: true
          contents:
            source: data:text/plain;charset=utf-8;base64,${HOSTNAME_B64}
EOF

# ==== IGNITION ====
echo "🚀 Generating ignition config..."
./openshift-install --dir=sno create single-node-ignition-config

# ==== IGNITION HACK: hostname + IPv6 disable direct in bootstrap ====
echo "🔨 Patching ignition with early hostname and IPv6 disable..."

# Complete NetworkManager keyfile: forceert deze connection over auto-detected
# Naam 'static-ethernet' wint van auto-gegenereerde 'Wired connection 1'
NM_KEYFILE=$(cat <<'NMEOF'
[connection]
id=static-ethernet
type=ethernet
autoconnect=true
autoconnect-priority=999

[ethernet]

[ipv4]
method=auto

[ipv6]
method=disabled

[proxy]
NMEOF
)
NM_KEYFILE_B64=$(echo "$NM_KEYFILE" | base64 | tr -d '\n')

# Sysctl config voor kernel-level IPv6 disable
SYSCTL_B64=$(echo 'net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1' | base64 | tr -d '\n')

cp sno/bootstrap-in-place-for-live-iso.ign sno/bootstrap-in-place-for-live-iso.ign.bak

jq --arg hostname_b64 "$HOSTNAME_B64" \
   --arg nm_keyfile_b64 "$NM_KEYFILE_B64" \
   --arg sysctl_b64 "$SYSCTL_B64" \
'.storage.files += [
  {
    "path": "/etc/hostname",
    "mode": 420,
    "overwrite": true,
    "contents": {
      "source": ("data:text/plain;charset=utf-8;base64," + $hostname_b64)
    }
  },
  {
    "path": "/etc/NetworkManager/system-connections/static-ethernet.nmconnection",
    "mode": 384,
    "overwrite": true,
    "contents": {
      "source": ("data:text/plain;charset=utf-8;base64," + $nm_keyfile_b64)
    }
  },
  {
    "path": "/etc/sysctl.d/95-disable-ipv6.conf",
    "mode": 420,
    "overwrite": true,
    "contents": {
      "source": ("data:text/plain;charset=utf-8;base64," + $sysctl_b64)
    }
  }
]' sno/bootstrap-in-place-for-live-iso.ign.bak > sno/bootstrap-in-place-for-live-iso.ign

# Verifieer
HOSTNAME_COUNT=$(grep -o "$HOSTNAME_B64" sno/bootstrap-in-place-for-live-iso.ign | wc -l | tr -d ' ')
echo "✅ Hostname references in ignition: $HOSTNAME_COUNT (expect at least 2)"

# ==== ISO BUILD ====
echo "💿 Resetting and rebuilding ISO..."

# Reset kernel args
docker run --rm --platform linux/amd64 -v "$(pwd):/data" -w /data \
  quay.io/coreos/coreos-installer:release \
  iso kargs reset scos-live.iso

# Embed ignition (--force om oude te overschrijven)
docker run --rm --platform linux/amd64 -v "$(pwd):/data" -w /data \
  quay.io/coreos/coreos-installer:release \
  iso ignition embed -f -i sno/bootstrap-in-place-for-live-iso.ign scos-live.iso

# Verifieer
echo "🔍 Verifying ISO..."
KARGS=$(docker run --rm --platform linux/amd64 -v "$(pwd):/data" -w /data \
  quay.io/coreos/coreos-installer:release \
  iso kargs show scos-live.iso)
echo "Kernel args: $KARGS"

IGN_CHECK=$(docker run --rm --platform linux/amd64 -v "$(pwd):/data" -w /data \
  quay.io/coreos/coreos-installer:release \
  iso ignition show scos-live.iso 2>/dev/null | grep -o "$HOSTNAME_B64" | wc -l | tr -d ' ')
echo "Hostname patches in ISO ignition: $IGN_CHECK"

# ==== KLAAR ====
echo ""
echo "✅ ALL DONE!"
echo ""
echo "📋 Next steps:"
echo "  1. Insert USB stick"
echo "  2. Find disk: diskutil list external"
echo "  3. Unmount:   diskutil unmountDisk /dev/diskN"
echo "  4. Flash:     sudo dd if=scos-live.iso of=/dev/rdiskN bs=1m status=progress"
echo "  5. Eject:     diskutil eject /dev/diskN"
echo ""
echo "🎯 Then boot the PC from USB with monitor attached."
echo "   Wait for login prompt, then SSH from MacBook:"
echo "     ssh-keygen -R $NODE_IP"
echo "     ssh -i ~/.ssh/okd-sno core@$NODE_IP"
echo ""
echo "   On the node, wipe the disk if needed (oude LVM van een vorige"
echo "   install kan install-to-disk blokkeren met 'found busy partitions' —"
echo "   vgchange EERST, anders krijgt dmsetup de VG niet los):"
echo "     sudo vgs                          # zoek de VG-naam, bv. ubuntu-vg"
echo "     sudo vgchange -an <vg-naam>"
echo "     sudo dmsetup remove_all 2>/dev/null"
echo "     sudo wipefs -a $INSTALLATION_DISK"
echo ""
echo "   Monitor install from MacBook:"
echo "     export KUBECONFIG=$WORKDIR/sno/auth/kubeconfig"
echo "     ./openshift-install --dir=sno wait-for install-complete --log-level=info"
echo ""
