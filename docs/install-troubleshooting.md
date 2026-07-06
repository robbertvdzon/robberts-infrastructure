# Install-troubleshooting — bekende problemen uit de originele install

De originele install (11-12 mei 2026) kostte **6 pogingen en ~18 uur** voordat
alles werkte. Elk van onderstaande problemen is al opgelost en verwerkt in
`~/build-okd-sno.sh` en de MachineConfigs in
[`../manifests/machineconfigs/`](../manifests/machineconfigs/) — dit document
is de lookup-tabel voor als iets tijdens een toekomstige rebuild ineens weer
bekend voelt. Bron: samenvatting door Robbert, `openshift-sno-rebuild.md`.

## Probleem 1 — one.com ondersteunt geen subdomain-delegation

**Symptoom**: `lab.vdzon.com` delegeren naar Cloudflare-nameservers lukt niet.
**Oorzaak**: one.com ondersteunt subdomain-delegation alleen op Enterprise-
plannen. **Fix**: DNS gewoon bij one.com houden, wildcards gebruiken (zie
[manual-external-steps.md](manual-external-steps.md)). Cloudflare blijft
alleen voor de Tunnels. **Les**: check dit vooraf bij een nieuwe DNS-provider.

## Probleem 2 — oude LVM blokkeert install-to-disk

**Symptoom**: `coreos-installer` faalt met
`Partitions in use on /dev/sda ... found busy partitions` als er nog een
oude Ubuntu-install met LVM op de schijf staat.
**Fix** — **ontbrak tot nu in dit playbook**, `vgchange` moet vóór
`dmsetup`/`wipefs`:
```bash
sudo vgchange -an ubuntu-vg      # (of de naam die `sudo vgs` toont)
sudo dmsetup remove_all 2>/dev/null
sudo wipefs -a /dev/sda
```
Zonder de `vgchange`-stap eerst kan `dmsetup remove_all` de actieve LVM niet
altijd loskrijgen. **Toegevoegd aan** [disaster-recovery-playbook.md](disaster-recovery-playbook.md)
stap 1.

## Probleem 3 — IPv6 SLAAC (Ziggo) brak drie dingen tegelijk

Zie [architecture.md](architecture.md) voor de definitieve fix
(NetworkManager-keyfile + sysctl, in ignition gebakken door
`build-okd-sno.sh`, plus `99-master-disable-ipv6` MachineConfig als vangnet).
Drie deelsymptomen om te herkennen als dit ooit terugkomt:

- **3a**: rare IPv6-hostname (`2001-1c04-...`) → `node-valid-hostname.service`
  hangt, bootkube komt niet verder dan het loginprompt.
- **3b**: `kube-apiserver` crasht met
  `service IP family "172.30.0.0/16" must match public address family "2001:..."`.
- **3c**: **niet** `ipv6.disable=1` als kernel-arg gebruiken — dat disabled de
  hele IPv6-kernelmodule, waarna OVN-scripts crashen
  (`sysctl: cannot stat /proc/sys/net/ipv6/conf/all/forwarding`, tot 38
  restarts gezien). De kernel-module moet blijven bestaan; IPv6 wordt
  uitgezet op interface-niveau (NetworkManager) + sysctl, niet op
  kernel-niveau.

## Probleem 4 — hostname niet valid tijdens bootstrap

**Symptoom**: cluster hangt op het login-prompt, hostname is
`localhost.localdomain`. **Oorzaak**: Ziggo-DHCP geeft geen hostname mee, en
`node-valid-hostname.service` (waar bootkube/kubelet/crio op wachten)
accepteert `localhost.localdomain` niet. **Fix**: `/etc/hostname` moet al in
de **ignition** staan (niet pas als MachineConfig — te laat, MCO is nog niet
actief tijdens bootstrap). Zie `99-master-hostname` MachineConfig
(post-bootstrap vangnet) en de ignition-patch in `build-okd-sno.sh`.

## Probleem 5 — misleidende "annotation not found"-fout (rode haring)

**Symptoom**: op één mislukte poging stond `service-ca` Pending met
`unable to find annotation openshift.io/sa.scc.uid-range`.
**Was niet de root cause** — een symptoom van dezelfde IPv6-problematiek
(chicken-and-egg keten van Pending operators). **Les**: bij zulke
annotation-fouten niet naar de annotation zelf kijken, maar naar de bredere
keten — meestal is er één root cause die veel operators blokkeert.

## Probleem 6 — DNS search-domain (console 60s+ traag)

Volledig gedocumenteerd in [architecture.md](architecture.md) en
[`manifests/machineconfigs/99-master-strip-bad-search-domain.yaml`](../manifests/machineconfigs/99-master-strip-bad-search-domain.yaml).
Kernsymptoom: pod-naar-pod-IP werkt, pod-naar-service-ClusterIP/-hostname
timeout't — lijkt op OVN, is DNS (one.com's wildcard `*.vdzon.com` vangt de
`ndots:5`-search-domain-expansie op).

## Probleem 7 — browsercache na DNS-wijzigingen

**Symptoom**: na het uitzetten van `AAAA *.vdzon.com` bij one.com bleef
Chrome het oude IPv6 gebruiken (`ERR_SSL_VERSION_OR_CIPHER_MISMATCH`,
`ERR_ADDRESS_UNREACHABLE`) terwijl Safari direct werkte.
**Fix**: `/etc/hosts` op de MacBook (zie [manual-external-steps.md](manual-external-steps.md))
werkt betrouwbaarder dan cache legen. Als je het toch via Chrome wil proberen:
`chrome://net-internals/#dns` (Clear host cache) → `#sockets` (Flush socket
pools) → eventueel `#hsts`. **Les**: DNS-caching zit op meerdere lagen (DNS-
provider-TTL, Ziggo-resolver, macOS mDNSResponder, browser) — na een grote
DNS-wijziging kan het uren duren voor alles synct. `/etc/hosts` omzeilt alle
lagen in één keer.

## Probleem 8 — ArgoCD-operator OperatorGroup-mismatch

**Symptoom**: Subscription voor `argocd-operator` faalt met
`OwnNamespace InstallModeType not supported, cannot configure to watch own
namespace`. **Oorzaak**: deze operator ondersteunt alleen `AllNamespaces`
install-mode; die moet in de speciale namespace `openshift-operators` staan
(heeft al een AllNamespaces OperatorGroup), niet in de `argocd`-namespace
zelf. **Status: al goed** in
[`personal-news-feed-by-claude-code/deploy/argocd-operator-subscription.yaml`](../../personal-news-feed-by-claude-code/deploy/argocd-operator-subscription.yaml)
— geverifieerd op de live cluster (`namespace: openshift-operators`, CSV
`Succeeded`). **Les voor de toekomst**: check bij een nieuwe operator eerst
`oc get packagemanifest <name> -o jsonpath='{.status.channels[0].currentCSVDesc.installModes}'`.

## Wat NIET te doen (na install)

- ❌ `sudo rpm-ostree kargs --append/--delete` — brengt MCO in conflict-state
- ❌ `sudo hostnamectl set-hostname` — MCO ziet dit als onbekende wijziging
- ❌ `sudo nmcli connection modify` op de node — wordt overschreven bij de
  volgende MCO-reconcile
- ✅ Alles via MachineConfig voor persistente node-wijzigingen; voor node-
  debugging `oc debug node/sno.lab.vdzon.com` i.p.v. losse SSH-wijzigingen

## Ontbrekend stuk in `~/build-okd-sno.sh`

Het script print zelf nog steeds alleen `dmsetup remove_all` + `wipefs -a`
als disk-wipe-instructie (zie hierboven, Probleem 2) — de `vgchange -an`-stap
staat er niet in. Dit playbook is bijgewerkt; het script zelf (buiten git, in
`~/build-okd-sno.sh`) nog niet — zeg het als je wil dat ik dat ook aanpas.
