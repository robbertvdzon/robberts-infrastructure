# Publieke app aansluiten: Cloudflare en Google Auth

Dit document beschrijft de actuele, gedeelde inrichting voor een nieuwe webapp op het
thuis-OpenShift-cluster. Het voorkomt dat bij iedere app opnieuw tunnels of Google-projecten
worden aangemaakt. Laatste praktijkcontrole: 2026-08-07, tijdens de voorbereiding van de
gezamenlijke OpenShift-ingressroute.

## 1. Cloudflare: de bestaande gedeelde tunnel gebruiken

`vdzonsoftware.nl` gebruikt Cloudflare DNS. Externe applicaties lopen door één remotely managed
Cloudflare Tunnel; er is geen inkomende router-port-forwarding. De actieve connector is de
Deployment `cloudflared` in namespace `personal-news-feed`. Het tunnel-token staat versleuteld in
de bestaande `newsfeed-api-keys` SealedSecret.

Een nieuwe app krijgt daarom normaal gesproken:

- geen eigen tunnel;
- geen nieuw `TUNNEL_TOKEN`;
- geen eigen Published application-route in Cloudflare;
- een Git-managed OpenShift `Route` met de volledige publieke hostnaam;
- automatisch bereik via de bestaande wildcard zodra die naar OpenShift ingress wijst.

`RA_HOME_ASSISTENT_TOKEN` uit Robberts Assistent is geen Cloudflare-token. Het is een Home
Assistant API-token en mag nooit voor tunnelconfiguratie worden gebruikt.

### Eén wildcard naar OpenShift ingress

De gewenste Cloudflare-configuratie bevat één algemene applicatieregel:

| Publieke hostname | Interne Service URL |
|---|---|
| `*.vdzonsoftware.nl` | `http://router-internal-default.openshift-ingress.svc.cluster.local:80` |

Laat **HTTP Host Header** op de standaardwaarde staan. Dan behoudt Cloudflare de oorspronkelijke
publieke hostnaam en kan OpenShift de juiste declaratieve `Route.spec.host` selecteren. In de
nieuwe Cloudflare-route-interface is hiervoor geen extra veld nodig.

De browserverbinding en de Cloudflare Tunnel zijn versleuteld. Alleen het laatste stuk van de
connector naar de OpenShift-router gebruikt HTTP binnen hetzelfde cluster, net als de bestaande
rechtstreekse servicekoppelingen. De publieke OpenShift Routes gebruiken daarom
`insecureEdgeTerminationPolicy: Allow`. Hiermee zijn geen uitgeschakelde certificaatcontroles of
extra origininstellingen in Cloudflare nodig.

Tijdens de overgang blijven de bestaande specifieke Cloudflare-routes als rollbackpad staan. Ze
worden pas één voor één verwijderd nadat dezelfde hostname via OpenShift ingress is getest.

### Veilige canary vóór de wildcardomschakeling

1. Maak in OpenShift tijdelijk een Route met host
   `wildcard-ingress-canary.vdzonsoftware.nl`; maak hiervoor juist geen specifieke
   Cloudflare-route.
2. Wijzig de service van de bestaande `*.vdzonsoftware.nl`-regel naar
   `http://router-internal-default.openshift-ingress.svc.cluster.local:80`.
3. Er zijn geen aanvullende TLS- of Host-headerinstellingen nodig.
4. Controleer dat de canary via de wildcard de applicatie bereikt die door de gelijknamige
   OpenShift Route is aangewezen. De bestaande specifieke productieroutes blijven tijdens deze
   test hun huidige services gebruiken.
5. Zet bij een fout de wildcardservice direct terug naar
   `http://preview-router.personal-news-feed.svc.cluster.local:80`.
6. Deploy daarna de Git-managed productie- en previewroutes en controleer alle productiehosts en
   minimaal één previewhost.
7. Verwijder de OpenShift-canary en daarna één voor één de overbodige specifieke
   Cloudflare-routes.

### Controleren

```bash
curl -i https://mijn-app.vdzonsoftware.nl/
oc logs -n personal-news-feed deploy/cloudflared --since=10m
```

Een bekende host hoort de bijbehorende applicatie terug te geven. Een onbekende wildcardhost hoort
een OpenShift-routerfout (`503` in de huidige routerconfiguratie) te geven en nooit stilzwijgend bij
een andere applicatie uit te komen.
Controleer ook zorgvuldig op typefouten; `khk` en `hkh` zijn verschillende DNS-records.

## 2. Google Auth: bestaand project en Web OAuth-client hergebruiken

De webapplicaties delen het bestaande Google Cloud-project `tuinbewatering`. Voor applicaties met
dezelfde beheerder en trust boundary wordt de bestaande OAuth-client van type **Web application**,
genaamd `Robberts applicaties`, hergebruikt. Maak niet automatisch een nieuw Google-project,
OAuth-client of client secret.

### Handmatige Google-stap

1. Open Google Cloud Console → Google Auth Platform → Clients.
2. Open Web OAuth-client `Robberts applicaties`.
3. Voeg iedere nieuwe adminsite toe onder **Authorized JavaScript origins**, als volledige origin
   zonder pad, bijvoorbeeld `https://mijn-app-admin.vdzonsoftware.nl`.
4. Voeg voor de huidige popup/callback-login niets toe onder **Authorized redirect URIs**.
5. Staat de app onder Audience nog in Testing, voeg dan ieder toegestaan beheeraccount ook als
   test user toe.

Alleen de publieke adminsite hoeft als JavaScript-origin geregistreerd te worden. Een gewone
gebruikersfrontend zonder Google-login niet. Een Android OAuth-client is pas nodig wanneer de APK
zelf Google-login krijgt; een APK die alleen een REST-API gebruikt heeft die client niet nodig.

### Applicatieconfiguratie

De Web OAuth client-ID is niet geheim, maar wordt wel centraal uit de bestaande configuratie
overgenomen. Een client secret wordt voor deze browserlogin en backend-ID-tokenverificatie niet
gebruikt.

Per repository zijn doorgaans nodig:

- GitHub Actions-variable `GOOGLE_CLIENT_ID`, omdat Flutter deze tijdens de admin-webbuild
  compileert;
- een publieke `API_BASE_URL` voor builds die niet same-origin kunnen werken, zoals Android;
- backend-runtimewaarde voor dezelfde Google client-ID;
- een komma-gescheiden admin-e-mailallowlist;
- de publieke admin-origin in de backend-CORS-configuratie;
- versleuteling van runtimewaarden met het bestaande Sealed Secrets-proces.

Na het wijzigen van een GitHub-variable moet de betreffende Flutter-image opnieuw worden gebouwd;
een bestaande image verandert niet achteraf. Na het wijzigen van een Kubernetes Secret moet de
backend een nieuwe pod krijgen om environmentvariabelen opnieuw in te lezen.

### Fail-closed controle

Zonder configuratie hoort de admin-API onbeschikbaar te zijn. Na geldige configuratie hoort een
request zonder bearer-token `401` te geven; `200` mag alleen volgen na een geldig Google ID-token
met de juiste audience, een geverifieerd e-mailadres en een e-mailadres uit de allowlist.

## 3. Onboardingchecklist

- [ ] Publieke hostname als `Route.spec.host` in de applicatierepository vastgelegd.
- [ ] Wildcard wijst naar de interne OpenShift-ingressrouter en behoudt de Host-header.
- [ ] Publieke URL geeft de bedoelde app; een onbekende host geeft een routerfout.
- [ ] Admin-origin toegevoegd aan de bestaande Google Web OAuth-client.
- [ ] Beheeraccount staat zo nodig als Google test user geregistreerd.
- [ ] Google client-ID, allowlist en CORS-origin via SealedSecret/runtimeconfig gezet.
- [ ] GitHub-buildvariabelen gezet en Flutter opnieuw gebouwd.
- [ ] Backend opnieuw uitgerold en admin-API geeft zonder token `401`.
- [ ] Login met een toegestaan én een niet-toegestaan Google-account getest.
