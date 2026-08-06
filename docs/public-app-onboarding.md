# Publieke app aansluiten: Cloudflare en Google Auth

Dit document beschrijft de actuele, gedeelde inrichting voor een nieuwe webapp op het
thuis-OpenShift-cluster. Het voorkomt dat bij iedere app opnieuw tunnels of Google-projecten
worden aangemaakt. Laatste praktijkcontrole: 2026-08-06, tijdens de aansluiting van `hkh` en
`hkh-autopilot`.

## 1. Cloudflare: de bestaande gedeelde tunnel gebruiken

`vdzonsoftware.nl` gebruikt Cloudflare DNS. Externe applicaties lopen door één remotely managed
Cloudflare Tunnel; er is geen inkomende router-port-forwarding. De actieve connector is de
Deployment `cloudflared` in namespace `personal-news-feed`. Het tunnel-token staat versleuteld in
de bestaande `newsfeed-api-keys` SealedSecret.

Een nieuwe app krijgt daarom normaal gesproken:

- geen eigen tunnel;
- geen nieuw `TUNNEL_TOKEN`;
- één Published application-route per publieke hostname in de bestaande tunnel;
- als Service URL de volledige interne Kubernetes-Service-FQDN, bijvoorbeeld
  `http://frontend.mijn-namespace.svc.cluster.local:8080`.

`RA_HOME_ASSISTENT_TOKEN` uit Robberts Assistent is geen Cloudflare-token. Het is een Home
Assistant API-token en mag nooit voor tunnelconfiguratie worden gebruikt.

### Wildcardregel moet de laatste hostnameregel zijn

De tunnel bevat `*.vdzonsoftware.nl`, gericht op
`http://preview-router.personal-news-feed.svc.cluster.local:80` voor PR-previews. `cloudflared`
evalueert ingressregels van boven naar beneden en gebruikt de eerste match. De wildcard moet dus
na alle specifieke hostnamen staan; alleen de verplichte `http_status:404`-catch-all volgt erna.

De huidige Cloudflare-interface voegt een nieuwe Published application-route onderaan toe, maar
biedt geen zichtbare sorteeractie. Staat de wildcard al in de lijst, gebruik dan deze procedure:

1. noteer Service URL en origin-instellingen van `*.vdzonsoftware.nl`;
2. verwijder tijdelijk alleen deze wildcardroute;
3. voeg alle nieuwe specifieke hostnamen toe;
4. maak `*.vdzonsoftware.nl` als laatste opnieuw aan met exact dezelfde instellingen;
5. controleer dat de connector een nieuwe configuratie heeft ontvangen.

Tijdens stap 2-4 zijn alleen PR-previewhostnamen kort niet bereikbaar. DNS-specificiteit lost dit
niet op: een specifiek DNS-record kiest wel de tunnel, maar binnen diezelfde tunnel blijft de
volgorde van de ingressregels bepalend.

Voor HKH is de gewenste configuratie:

| Publieke hostname | Interne Service URL |
|---|---|
| `hkh.vdzonsoftware.nl` | `http://frontend.hkh.svc.cluster.local:8080` |
| `hkh-admin.vdzonsoftware.nl` | `http://admin.hkh.svc.cluster.local:8080` |
| `hkh-autopilot.vdzonsoftware.nl` | `http://frontend.hkh-autopilot.svc.cluster.local:8080` |
| `hkh-autopilot-admin.vdzonsoftware.nl` | `http://admin.hkh-autopilot.svc.cluster.local:8080` |
| `*.vdzonsoftware.nl` | `http://preview-router.personal-news-feed.svc.cluster.local:80` — laatste hostnameregel |

### Controleren

```bash
curl -i https://mijn-app.vdzonsoftware.nl/
oc logs -n personal-news-feed deploy/cloudflared --since=10m
```

Een antwoord `Onbekende preview-hostname` komt van de preview-router en bewijst dat de wildcard
de aanvraag ten onrechte vóór de specifieke regel heeft onderschept. Controleer ook zorgvuldig op
typefouten in de hostname; `khk` en `hkh` zijn verschillende DNS-records.

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

- [ ] Publieke hostname en interne Service URL bepaald.
- [ ] Specifieke tunnelroute toegevoegd vóór de wildcard.
- [ ] Wildcard `*.vdzonsoftware.nl` staat als laatste hostnameregel, vóór de 404-catch-all.
- [ ] Publieke URL geeft de bedoelde app en niet `Onbekende preview-hostname`.
- [ ] Admin-origin toegevoegd aan de bestaande Google Web OAuth-client.
- [ ] Beheeraccount staat zo nodig als Google test user geregistreerd.
- [ ] Google client-ID, allowlist en CORS-origin via SealedSecret/runtimeconfig gezet.
- [ ] GitHub-buildvariabelen gezet en Flutter opnieuw gebouwd.
- [ ] Backend opnieuw uitgerold en admin-API geeft zonder token `401`.
- [ ] Login met een toegestaan én een niet-toegestaan Google-account getest.
