# Golfturnering – løbende Stableford-stilling

Lille webapp til en turnering over tre runder (fredag 18., lørdag 19. og søndag 20. september 2026).
Alle, der har adressen, kan åbne den på telefonen, tilmelde sig og taste slag hul for hul.

## Sådan virker den

* **Tilmelding:** navn og DGU-handicap (HCP-index), og valg af tee hvis runden har flere. Appen
  omregner til spillehandicap efter WHS: HCP-index × slope ÷ 113 + (course rating − par), ganget
  med handicaptildelingen (100 % som standard, 95 % kan vælges) og rundet til hele slag. Med 100 %
  giver det præcis de samme tal som klubbens course handicap table (testet mod DGU's tabel for
  Samsø Golfklub, tee 56). Slagene fordeles efter banens handicapnøgle.
* **Scorekort:** tryk på et hul og vælg antal slag på taltastaturet. Stablefordpointene regnes ud
  med det samme, og tastaturet springer selv videre til næste hul. *Streg* = hullet opgivet (0 point).
* **Stilling:** ranglisten for runden opdateres hvert par sekunder hos alle. Pile viser, hvem der er
  rykket op og ned siden sidst. Ved lige Stablefordpoint står den med laveste HCP-index øverst.
* **Runden er færdig,** når alle tilmeldte (som ikke er sat til *spiller ikke*) har tastet 18 huller.
  Så vises rundens vinder og turneringspointene: vinderen får *antal deltagere + 2*, nr. 2 får
  *antal deltagere − 1*, og så videre ned til 1 point til sidstepladsen. Med 18 deltagere får
  vinderen altså 20, nr. 2 får 17 og nr. 18 får 1.
* **Samlet:** turneringspoint lagt sammen over de tre runder. Ved lighed tæller flest
  Stablefordpoint i alt, derefter laveste HCP-index.
* **Opsætning (tandhjulet):** turneringens navn, bane, ét eller flere tees med course rating og
  slope, par og handicapnøgle pr. hul for hver runde (*Kopiér bane til alle runder* sparer tid),
  *Luk runden nu* hvis nogen aldrig får tastet færdig, og sletning af spillere. Sæt en PIN i `.env`
  (`GOLF_PIN`), så kun du kan gøre de ting – tilmelding og scoreindtastning kræver aldrig PIN.

Standardopsætningen er **Samsø Golfklub, 18 hullers bane, tee 56 (herrer): par 72, course rating
70,8, slope 131**. Par og handicapnøgle pr. hul er derimod en generisk par 72-fordeling, så inden
turneringen skal du under Opsætning taste par og nøgle for hvert hul fra klubbens scorekort og trykke
*Kopiér bane til alle runder*. Spiller nogen fra tee 49 eller 61, tilføjer du dem som tees med
tallene fra klubbens konverteringstabel, og spillerne vælger så selv tee ved tilmelding.

## Prøv den på din egen pc

```bash
cd innermind_regnskab
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn golf.server:app --host 0.0.0.0 --port 8010
```

Åbn <http://localhost:8010>. På Windows kan du i stedet dobbeltklikke på `golf\start.bat`. Data
gemmes i `golf/data/golf.json`. Andre på samme wi-fi kan bruge `http://<din-ip>:8010`, men skal
spillerne kunne taste ude på banen, skal appen ligge på en server på internettet – se næste afsnit.

Åbner du `golf/static/index.html` direkte i en browser uden server, kører appen i prøveversion, hvor
alt kun gemmes i den browser. Det er fint til at kigge, men ikke til selve turneringen.

## Sæt den på en server (alle kan nå den fra telefonen)

Fremgangsmåden er den samme som for regnskabsprogrammet i `DEPLOY.md`: en lille server hos fx
Hetzner (den mindste er rigelig og kan slettes igen efter turneringen), Docker og et domæne eller
serverens IP via sslip.io.

1. Opret serveren og installér Docker som i `DEPLOY.md`, trin 1–2.
2. Hent programmet og gå til golf-mappen:

   ```bash
   cd /opt
   git clone https://github.com/erikjul/innermind_regnskab.git
   cd innermind_regnskab/golf
   cp .env.example .env
   nano .env
   ```

   Sæt `GOLF_DOMAENE` (fx `golf.innermind.dk` med en A-record til serverens IP, eller
   `65-108-1-2.sslip.io` med serverens IP skrevet med bindestreger) og eventuelt `GOLF_PIN`.
3. Start:

   ```bash
   docker compose up -d --build
   ```

   Efter et halvt minut svarer `https://<GOLF_DOMAENE>`. Send adressen til spillerne – de kan lægge
   den på hjemmeskærmen på telefonen, så den opfører sig som en app.

**Kører regnskabsprogrammet allerede på samme server?** Så er port 80/443 optaget af dets Caddy.
Brug enten en separat server til golf (nemmest), eller tilføj golf-appen som en service i
hovedmappens `docker-compose.yml` og en ekstra site-blok i `deploy/Caddyfile`, der peger på
`golf:8010`.

Opdatering: `git pull && docker compose up -d --build` i golf-mappen. Data ligger i Docker-volumen
`golf_golf_data` og overlever opdateringer. En kopi af data hentes med
`docker compose cp golf:/data/golf.json .`.

## Tests

```bash
pytest tests/test_golf.py
```

Beregningerne (spillehandicap, Stableford, turneringspoint) ligger i `static/scoring.js` og testes med
node; API'et testes med FastAPI's testklient.
