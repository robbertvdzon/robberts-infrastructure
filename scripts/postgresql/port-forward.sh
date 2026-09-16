#!/usr/bin/env bash
# Open local-only tunnels to the two central PostgreSQL services.
# Requires an existing, authorized `oc login`; it never reads credentials.
set -euo pipefail

if ! command -v oc >/dev/null 2>&1; then
  echo 'oc is required; install the OpenShift CLI and log in first.' >&2
  exit 1
fi

case "${1:-all}" in
  all) targets=('postgres-production:15432' 'postgres-nonproduction:15433') ;;
  production) targets=('postgres-production:15432') ;;
  nonproduction) targets=('postgres-nonproduction:15433') ;;
  *)
    echo "Usage: $0 [all|production|nonproduction]" >&2
    exit 2
    ;;
esac

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

for target in "${targets[@]}"; do
  namespace=${target%%:*}
  port=${target##*:}
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Local port $port is already in use; stop that process or choose another port." >&2
    exit 1
  fi
  oc port-forward --address 127.0.0.1 -n "$namespace" svc/postgres "$port":5432 >/dev/null 2>&1 &
  pids+=("$!")
done

sleep 1
for pid in "${pids[@]}"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo 'A PostgreSQL tunnel could not be started; verify your oc login and access.' >&2
    exit 1
  fi
done

printf '%s\n' \
  'PostgreSQL tunnels are active:' \
  '  production:     127.0.0.1:15432' \
  '  non-production: 127.0.0.1:15433' \
  'Press Ctrl-C to close them.'
wait
