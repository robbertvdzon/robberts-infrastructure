# Install-tools downloaden (nieuwe laptop / opgeschoonde `~/okd-sno`)

Deze 3 dingen horen in `~/okd-sno/` te staan vóór je
[`scripts/install/build-okd-sno.sh`](../scripts/install/build-okd-sno.sh) kan
draaien. Geen van drieën is geheim of uniek — allemaal gewoon opnieuw te
downloaden, geen backup van nodig (in tegenstelling tot `pull-secret.txt`,
zie onderaan).

Huidige gebruikte versie: **`4.21.0-okd-scos.10`** (zie
[architecture.md](architecture.md)). Voor `mac-arm64` (Apple Silicon) — gebruik
`mac-` i.p.v. `mac-arm64-` in de bestandsnamen hieronder op een Intel-Mac.

## 1. `openshift-install` + `oc`/`kubectl`

Via GitHub CLI (`gh`, al geïnstalleerd als je deze repo gebruikt):

```bash
mkdir -p ~/okd-sno && cd ~/okd-sno
VERSION="4.21.0-okd-scos.10"

gh release download "$VERSION" --repo okd-project/okd \
  --pattern "openshift-install-mac-arm64-*.tar.gz" \
  --pattern "openshift-client-mac-arm64-*.tar.gz"

tar xzf "openshift-install-mac-arm64-$VERSION.tar.gz"
tar xzf "openshift-client-mac-arm64-$VERSION.tar.gz"
chmod +x openshift-install oc kubectl
```

Zonder `gh`: dezelfde bestanden staan op
`https://github.com/okd-project/okd/releases/tag/4.21.0-okd-scos.10` — download
`openshift-install-mac-arm64-4.21.0-okd-scos.10.tar.gz` en
`openshift-client-mac-arm64-4.21.0-okd-scos.10.tar.gz` handmatig en pak ze
op dezelfde manier uit in `~/okd-sno/`.

**Nieuwere versie willen?** `gh release list --repo okd-project/okd --limit 10`
— dan wel `docs/architecture.md` bijwerken met de nieuwe versie, en er rekening
mee houden dat dit een ANDERE cluster-versie oplevert dan "exact hetzelfde
als nu".

## 2. `scos-live.iso`

Deze hangt aan de **specifieke `openshift-install`-versie** hierboven (niet
los te kiezen) — vraag het aan het binary zelf, dat garandeert dat ISO en
installer bij elkaar passen:

```bash
cd ~/okd-sno
ISO_URL=$(./openshift-install coreos print-stream-json | \
  jq -r '.architectures.x86_64.artifacts.metal.formats.iso.disk.location')
echo "$ISO_URL"
curl -L -o scos-live.iso "$ISO_URL"
```

(Voor de huidige versie is dat
`https://rhcos.mirror.openshift.com/art/storage/prod/streams/c10s/builds/10.0.20251103-0/x86_64/scos-10.0.20251103-0-live-iso.x86_64.iso`
— maar laat het commando dit opzoeken, niet hardcoden, want dit verandert
mee met de installer-versie.)

## 3. `pull-secret.txt` — WEL bewaren, in 1Password

Dit is je Red Hat-account-credential, niet iets herdownloadbaar. Zet 'm nu
in 1Password (als dat nog niet zo is):

```bash
cat ~/okd-sno/pull-secret.txt | pbcopy
```

Nieuw 1Password-item aanmaken (bv. "OpenShift SNO — pull-secret", type
Secure Note), plak de inhoud, opslaan. `pbcopy` zorgt dat de inhoud niet in
je terminal-historie of een chatvenster belandt.

**Terugzetten op een nieuwe laptop / na opschonen:**
```bash
mkdir -p ~/okd-sno
pbpaste > ~/okd-sno/pull-secret.txt   # nadat je 'm uit 1Password gekopieerd hebt
```

Heb je geen 1Password-kopie: nieuwe pull-secret ophalen via
`https://console.redhat.com/openshift/install/pull-secret` (inloggen met je
Red Hat-account) en op dezelfde manier opslaan.
