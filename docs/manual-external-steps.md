# Handmatige stappen buiten het cluster

Dit zijn de dingen die niet in een script zitten omdat ze in externe systemen
leven (DNS-provider, router, Cloudflare-dashboard) of eenmalig tijdens de
fysieke install gebeuren. Ze overleven een OpenShift-reinstall vanzelf
(ze staan niet ín de cluster) — deze pagina is zodat je weet dat ze bestaan en
kan verifiëren dat ze nog kloppen.

## DNS bij one.com (`vdzon.com`)

Onder "Persoonlijke DNS-instellingen":
- `A vdzon.com → 192.0.78.24` / `192.0.78.25` (one.com hosting, niet gerelateerd aan de cluster)
- `A *.apps.sno.lab.vdzon.com → 192.168.178.64`
- `A api-int.sno.lab.vdzon.com → 192.168.178.64`
- `A api.sno.lab.vdzon.com → 192.168.178.64`

Onder "Standaard DNS-instellingen":
- `A *.vdzon.com` — AAN (dit is de catchall die het DNS-probleem veroorzaakt, zie
  [architecture.md](architecture.md); wordt binnen de cluster opgevangen door de
  `99-master-strip-bad-search-domain` MachineConfig, dus dit hoeft niet te
  wijzigen)
- `AAAA *.vdzon.com` — **UIT laten staan**. Als deze AAN staat, proberen browsers
  IPv6 naar de Ziggo-publieke-IPv6 van de node en krijg je
  `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` / `ERR_ADDRESS_UNREACHABLE`.

Geen PTR-records nodig (one.com ondersteunt dat niet voor privé-IP's, en het is
niet nodig voor de cluster).

## Ziggo router

DHCP-reservation: MAC `24:4B:FE:82:0D:4D` → `192.168.178.64`. Zorgt dat de node
na elke reboot hetzelfde IP krijgt. Geen port-forwarding nodig — alle externe
toegang loopt via uitgaande Cloudflare Tunnels.

## Cloudflare Tunnels

Publieke apps delen één remotely managed tunnel met de connector `cloudflared` in namespace
`personal-news-feed`. Een nieuwe app krijgt normaal alleen een Published application-route naar
zijn interne Kubernetes-Service en geen eigen tunnel of token. De wildcard
`*.vdzonsoftware.nl` voor PR-previews moet als laatste hostnameregel staan, vóór de verplichte
404-catch-all.

De volledige onboardingprocedure, inclusief de workaround voor de Cloudflare-interface zonder
sorteeractie en de gedeelde Google Web OAuth-client, staat in
[public-app-onboarding.md](public-app-onboarding.md).

## `/etc/hosts` op de MacBook (workaround, niet altijd nodig)

Als de console niet laadt door de AAAA-cache-issue hierboven:
```
192.168.178.64 console-openshift-console.apps.sno.lab.vdzon.com
192.168.178.64 oauth-openshift.apps.sno.lab.vdzon.com
192.168.178.64 api.sno.lab.vdzon.com
192.168.178.64 downloads-openshift-console.apps.sno.lab.vdzon.com
```

## Eenmalige fysieke/install-stappen

- `/dev/sda`-wipe vóór een reinstall als er nog een vorige install op staat
  (`dmsetup remove_all`, `wipefs -a /dev/sda`) — zie
  [disaster-recovery-playbook.md](disaster-recovery-playbook.md) stap 1.
- Bij de 12TB-schijf-swap: fysiek een schijf omwisselen — zie
  [disk-4tb-to-12tb-migration.md](disk-4tb-to-12tb-migration.md).
