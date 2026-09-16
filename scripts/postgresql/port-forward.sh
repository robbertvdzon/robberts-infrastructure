#!/usr/bin/env bash
# Open resilient, local-only tunnels to the central PostgreSQL services.
# Requires an existing, authorized `oc login`; it never reads credentials.
set -euo pipefail

if ! command -v oc >/dev/null 2>&1; then
  echo 'oc is required; install the OpenShift CLI and log in first.' >&2
  exit 1
fi

case "${1:-all}" in
  all) targets=('production:postgres-production:15432' 'non-production:postgres-nonproduction:15433') ;;
  production) targets=('production:postgres-production:15432') ;;
  nonproduction) targets=('non-production:postgres-nonproduction:15433') ;;
  *)
    echo "Usage: $0 [all|production|nonproduction]" >&2
    exit 2
    ;;
esac

pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

keep_tunnel_open() {
  local label=$1 namespace=$2 port=$3
  while true; do
    printf 'Connecting %s PostgreSQL tunnel on 127.0.0.1:%s ...\n' "$label" "$port"
    if oc port-forward --address 127.0.0.1 -n "$namespace" svc/postgres "$port":5432; then
      status=0
    else
      status=$?
    fi
    printf '%s PostgreSQL tunnel stopped (exit %s); retrying in 3 seconds.\n' "$label" "$status" >&2
    sleep 3
  done
}

for target in "${targets[@]}"; do
  IFS=: read -r label namespace port <<<"$target"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Local port $port is already in use; stop that process or choose another port." >&2
    exit 1
  fi
  keep_tunnel_open "$label" "$namespace" "$port" &
  pids+=("$!")
done

printf '%s\n' 'PostgreSQL tunnels will keep reconnecting until you press Ctrl-C:'
for target in "${targets[@]}"; do
  IFS=: read -r label namespace port <<<"$target"
  printf '  %-15s 127.0.0.1:%s\n' "$label:" "$port"
done
printf '%s\n' 'Press Ctrl-C to close them.'

wait
