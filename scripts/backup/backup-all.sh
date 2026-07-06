#!/usr/bin/env bash
#
# Backup alles wat je nodig hebt om na een reinstall exact terug te komen waar
# je nu staat. Read-only richting de cluster — wijzigt niets, exporteert alleen.
#
# Zie ../../docs/backup-and-restore.md voor de uitleg per item.
#
# Output: backups/<timestamp>/ in deze repo (gitignored — kopieer 'm zelf naar
# iets buiten deze laptop na afloop).
#
# Vereisten: oc ingelogd (KUBECONFIG of SF_KUBECONFIG), ssh-toegang tot de node.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="$REPO_ROOT/backups/$TS"

OKD_SNO_DIR="$HOME/okd-sno"
SSH_KEY="$HOME/.ssh/okd-sno"
SF_REPO="$HOME/git/softwarefactory"
PNF_REPO="$HOME/git/personal-news-feed-by-claude-code"

mkdir -p "$OUT"
echo "[backup] output: $OUT"

if ! oc whoami >/dev/null 2>&1; then
  echo "Error: 'oc whoami' faalt — ben je ingelogd? Check 'oc login' of KUBECONFIG." >&2
  exit 1
fi
echo "[backup] cluster: $(oc whoami --show-server)"

# ─── 1. Sealed-secrets private key(s) — HET belangrijkste item ───────────
echo
echo "[1/6] sealed-secrets private key(s)"
oc get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > "$OUT/sealed-secrets-keys.yaml"
n_keys=$(grep -c '^    name: sealed-secrets-key' "$OUT/sealed-secrets-keys.yaml" || true)
echo "       $n_keys key(s) weggeschreven naar sealed-secrets-keys.yaml"

# ─── 2. Cluster-admin toegang + install-inputs ────────────────────────────
echo
echo "[2/6] ~/okd-sno auth + install-inputs"
mkdir -p "$OUT/okd-sno"
for f in sno/auth/kubeconfig sno/auth/kubeadmin-password install-config.yaml pull-secret.txt; do
  if [[ -f "$OKD_SNO_DIR/$f" ]]; then
    mkdir -p "$OUT/okd-sno/$(dirname "$f")"
    cp "$OKD_SNO_DIR/$f" "$OUT/okd-sno/$f"
    echo "       ok: $f"
  else
    echo "       ontbreekt: $f (skip)"
  fi
done
# build-okd-sno.sh hoeft hier niet meer bij: zit al in deze repo
# (scripts/install/build-okd-sno.sh), dus al veilig in git + GitHub.

# ─── 3. SSH key voor de node ───────────────────────────────────────────────
echo
echo "[3/6] SSH key (~/.ssh/okd-sno)"
if [[ -f "$SSH_KEY" ]]; then
  mkdir -p "$OUT/ssh"
  cp "$SSH_KEY" "$SSH_KEY.pub" "$OUT/ssh/" 2>/dev/null || true
  chmod 600 "$OUT/ssh/okd-sno" 2>/dev/null || true
  echo "       ok"
else
  echo "       ontbreekt (skip)"
fi

# ─── 4. Live MachineConfigs (diff-vangnet t.o.v. manifests/machineconfigs/) ─
echo
echo "[4/6] live MachineConfigs (diff-check)"
mkdir -p "$OUT/machineconfigs-live"
for mc in 50-local-storage-mount 99-master-strip-bad-search-domain; do
  if oc get machineconfig "$mc" -o yaml >/dev/null 2>&1; then
    oc get machineconfig "$mc" -o yaml > "$OUT/machineconfigs-live/$mc.yaml"
    committed="$REPO_ROOT/manifests/machineconfigs/$mc.yaml"
    if [[ -f "$committed" ]]; then
      # vergelijk alleen spec, niet metadata/annotations/resourceVersion
      live_spec=$(python3 -c "import yaml,sys; print(yaml.dump(yaml.safe_load(open('$OUT/machineconfigs-live/$mc.yaml'))['spec']))" 2>/dev/null || echo "")
      committed_spec=$(python3 -c "import yaml,sys; print(yaml.dump(yaml.safe_load(open('$committed'))['spec']))" 2>/dev/null || echo "")
      if [[ "$live_spec" != "$committed_spec" ]]; then
        echo "       WAARSCHUWING: $mc wijkt af van manifests/machineconfigs/$mc.yaml — commit de live versie of onderzoek waarom"
      else
        echo "       ok: $mc komt overeen met git"
      fi
    else
      echo "       WAARSCHUWING: $mc bestaat live maar niet in manifests/machineconfigs/"
    fi
  else
    echo "       ontbreekt live: $mc"
  fi
done

# ─── 5. Plaintext secrets-bronnen (gitignored in de app-repo's) ───────────
echo
echo "[5/6] secrets.env / secrets-cluster.env uit app-repo's"
mkdir -p "$OUT/app-secrets"
# Simpele lijst i.p.v. associative array — macOS' meegeleverde /bin/bash is
# 3.2 (geen declare -A support, dat kwam pas in bash 4).
copy_app_secret() {
  local name="$1" src="$2"
  if [[ -f "$src" ]]; then
    cp "$src" "$OUT/app-secrets/$name"
    echo "       ok: $name"
  else
    echo "       ontbreekt: $src (skip)"
  fi
}
copy_app_secret "softwarefactory-secrets.env" "$SF_REPO/secrets.env"
copy_app_secret "personal-news-feed-secrets-cluster.env" "$PNF_REPO/deploy/secrets-cluster.env"

# ─── 6. Samenvatting ───────────────────────────────────────────────────────
echo
echo "[6/6] samenvatting"
find "$OUT" -type f | sed "s|$OUT/|       |"

cat > "$OUT/MANIFEST.txt" <<EOF
Backup gemaakt op: $TS
Cluster: $(oc whoami --show-server)

Bevat private keys en plaintext secrets. NIET in git (zie .gitignore).
Kopieer deze map naar een encrypted USB-stick of 1Password en verwijder 'm
daarna van deze laptop als je 'm niet meer nodig hebt.
EOF

echo
echo "[backup] klaar: $OUT"
echo "[backup] BELANGRIJK: kopieer deze map nu naar iets buiten deze laptop."
