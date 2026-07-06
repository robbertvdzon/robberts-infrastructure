#!/bin/bash
# NetworkManager dispatcher script.
# Strip lab.vdzon.com from /etc/resolv.conf search line.
# Why: upstream DNS for vdzon.com returns a catchall A record
# (46.30.213.97 / one.com hosting) instead of NXDOMAIN, which
# breaks pod ndots:5 lookups for *.cluster.local services.
#
# Dit bestand wordt NIET direct gebruikt — het is de leesbare bron van de
# base64-blob in ../../manifests/machineconfigs/99-master-strip-bad-search-domain.yaml.
# Als je dit script wijzigt, moet je de base64 in die MachineConfig opnieuw genereren:
#   base64 -i 30-strip-bad-search-domain.sh
EVENT="$2"
case "$EVENT" in
  up|dhcp4-change|dhcp6-change|reapply)
    if grep -qE '(^| )lab\.vdzon\.com( |$)' /etc/resolv.conf 2>/dev/null; then
      sed -i -E '
        s/(^|[[:space:]])lab\.vdzon\.com([[:space:]]|$)/\1\2/g
        s/[[:space:]]+/ /g
        s/^[[:space:]]+//
        s/[[:space:]]+$//
        /^search[[:space:]]*$/d
      ' /etc/resolv.conf
    fi
    ;;
esac
