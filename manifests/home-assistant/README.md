# Home Assistant

Draait als gewone Deployment op de SNO-node, LAN-only bereikbaar via een
OpenShift Route (`home-assistant.apps.sno.lab.vdzon.com`, valt onder de
bestaande wildcard-DNS). Bewust géén Cloudflare Tunnel: Home Assistant
bestuurt fysieke dingen in huis, en zonder port-forwarding op de router is
de Route sowieso al alleen bereikbaar vanaf het eigen netwerk (of via VPN).

## Storage — bewust gesplitst over twee plekken

Home Assistant's `/config` bevat twee heel verschillende soorten data:

- **Kritiek, niet-zelf-herstellend**: `.storage/*.json` (integraties,
  entity/device-registry, dashboards, gebruikers), `configuration.yaml`,
  `automations.yaml`. Kwijtraken hiervan betekent niet "een beetje data
  weg" — het betekent Home Assistant grotendeels opnieuw configureren,
  inclusief eventueel Zigbee/Z-Wave-apparaten opnieuw pairen.
- **Disposable, zelf-herstellend**: `home-assistant_v2.db` (de recorder —
  history/logbook/long-term-statistics). Leeg beginnen na een reinstall is
  vervelend maar geen werk: het vult zich vanzelf weer vanaf dat moment.

Die twee staan daarom op verschillende storage:

| Wat | Waar | Reinstall-proof? |
|---|---|---|
| `/config` (alles behalve de db) | `hostPath` op de externe 16TB-HDD (`/var/mnt/external-hdd/home-assistant`) | Ja, automatisch — een OS-reinstall raakt alleen de node-schijf, niet deze losse USB-drive. Geen aparte backup-stap nodig voor dit deel. |
| `home-assistant_v2.db` | losse PVC (`local-path`, 2Gi) | Nee, bewust — `local-path` is `hostPath` onder `/var/lib/local-path-provisioner` óp de node-OS-schijf, dus wél weg bij een reinstall. Acceptabel voor dit bestand. |

**Waarom niet gewoon alles op de HDD?** exFAT (de HDD is exFAT, zie
[../../docs/architecture.md](../../docs/architecture.md)) heeft geen
journaling en beperktere fsync/locking-garanties dan ext4. Voor
`.storage/*.json` maakt dat weinig uit — dat zijn simpele hele-bestand
writes. Voor `home-assistant_v2.db` (constante SQLite-transacties, elke
sensor-update) is dat wél een reëel corruptierisico, vooral na een
stroomstoring op deze single-node-cluster zonder redundantie. Vandaar de
knip via HA's eigen `recorder.db_url`-optie (zie
`configmap-default-config.yaml`) in plaats van het hele `/config` op de db
mee te laten liften.

**Waarom niet gewoon alles op een PVC?** Dan is het omgekeerde probleem:
het kritieke deel (`.storage/`, dashboards, integraties) is dan NIET
reinstall-proof en zou een aparte backup/restore-procedure nodig hebben
(HA's eigen snapshot-feature + een cronjob) om niet alles opnieuw te
moeten configureren. Direct op de HDD zetten is simpeler: het staat er
gewoon, altijd, zonder extra mechanisme.

## Overige keuzes

- **`hostNetwork: true`**: mDNS/SSDP-discovery (Chromecast, HomeKit,
  ESPHome, Sonos, enz.) werkt niet betrouwbaar door de pod-overlay heen —
  zelfde reden als avahi bij [../smb-timemachine](../smb-timemachine).
- **SCC `privileged`**: eerste poging was `hostmount-anyuid` (minder
  rechten, alleen hostPath), maar die staat geen `hostNetwork: true` toe —
  gaf `FailedCreate`/"Host network is not allowed to be used" en geen
  enkele pod kwam op. `privileged` is de enige SCC die hostPath +
  hostNetwork + hostPort samen toestaat (zelfde reden als bij
  smb-timemachine).
- **initContainer**: permissie-vangnet (zelfde les als smb-timemachine —
  zie die README) + seed van `configuration.yaml` **alleen als die nog niet
  bestaat**, zodat een latere handmatige wijziging nooit overschreven
  wordt.
- **`nodeSelector: kubernetes.io/hostname: sno.lab.vdzon.com`**: hardcoded,
  klopt zolang dit een SNO-cluster blijft (nodig omdat de hostPath alleen
  op deze node bestaat).

## Installeren — via ArgoCD (onderdeel van de root-app)

Alles hier staat in git en wordt door ArgoCD gesynct — geen `oc`/`ssh`
nodig. De Application-pointer staat in
[`../root-app/apps/home-assistant-application.yaml`](../root-app/apps/home-assistant-application.yaml).
Na de eerste sync: naar `https://home-assistant.apps.sno.lab.vdzon.com` (op
het LAN) en door de gebruikelijke HA-onboarding-wizard heen. Zet daarna
meteen MFA (TOTP) aan onder je gebruikersprofiel — wachtwoord-only is
alleen bedoeld als eerste beschermingslaag zolang dit LAN-only blijft.

## Gevonden en gefixt tijdens het testen (nuttig bij toekomstige wijzigingen)

1. `hostmount-anyuid`-SCC (eerste poging) staat geen `hostNetwork: true` toe
   — pod kwam nooit op (`FailedCreate`). Opgelost door `privileged` (zie
   `rolebinding-scc.yaml`).
2. Zonder `http.trusted_proxies` gaf elk verzoek via de Route een
   `400 Bad Request` ("your HTTP integration is not set-up for reverse
   proxies") — HA vertrouwt de OpenShift Router niet standaard. Opgelost
   door `192.168.178.64` (het node-IP) expliciet te vertrouwen in
   `configmap-default-config.yaml`.
3. Onschuldige, genegeerde warnings in de logs: Bluetooth-integratie mist
   `NET_ADMIN`/`NET_RAW` (geen Bluetooth-hardware relevant hier) en
   `aiodhcpwatcher` kan geen raw DHCP-packets lezen. Beide zijn optionele
   auto-discovery-features uit `default_config:`, niet blokkerend.

## Bekende beperkingen

- Geen backup van `home-assistant_v2.db` (bewust, zie boven — disposable).
- Geen backup van `/config` op de HDD tegen schijf-falen zelf (single point
  of failure, zelfde situatie als de Time Machine-data nu al). Los
  aandachtspunt, niet opgelost in deze opzet.
