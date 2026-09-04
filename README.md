# InnerMind Regnskab

Digitalt bogføringsprogram til en dansk enkeltmandsvirksomhed. Du uploader fakturaer og kvitteringer
(PDF, PNG, JPG, HEIC – også fotos taget med telefonens kamera), programmet aflæser dem automatisk,
foreslår konto og momskode, og efter din godkendelse bogføres bilaget, og momsen registreres i
momsregnskabet.

Programmet er bygget til at understøtte kravene i **bogføringsloven** (lov nr. 700 af 24. maj 2022).
Se afsnittet *Bogføringsloven* nederst for, hvad programmet gør, og hvad du selv skal sørge for.

## Sådan kommer du i gang

Kræver Python 3.11 eller nyere.

```bash
git clone <dette repo>
cd innermind_regnskab
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # indsæt din ANTHROPIC_API_KEY
export $(cat .env | xargs)                             # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Åbn derefter <http://localhost:8000>. Ved første start oprettes databasen, standardkontoplanen,
momskoderne og virksomhedsoplysningerne (InnerMind, CVR 38273337) automatisk. Ret dem under
*Indstillinger*.

For at tage billeder med telefonen: åbn adressen på computerens IP i telefonens browser på samme
netværk (fx `http://192.168.1.10:8000/bilag/upload`) og tryk *Tag et foto med kameraet*. Kør programmet
bag HTTPS (fx via Tailscale eller en reverse proxy), hvis det skal bruges uden for hjemmenetværket.

Aflæsningen bruger Claude API'et (modellen `claude-opus-5` som standard, kan ændres med
`REGNSKAB_CLAUDE_MODEL`). Uden API-nøgle virker alt andet stadig – du udfylder så felterne selv.
Programmet er sat op med serverside-fallback, så en aflæsning, som modellen afviser, automatisk
prøves igen på en anden Claude-model.

Kør testene med:

```bash
pytest
```

## Arbejdsgang

1. **Upload bilag** – filen gemmes uændret som originalbilag med fortløbende bilagsnummer og
   SHA-256-kontrolsum under `data/bilag/<år>/`. Dubletter (samme fil) markeres.
2. **Aflæsning** – bilaget sendes til Claude, som returnerer modpart, CVR, fakturanummer, dato,
   beløb, moms og et forslag til konto og momskode i et fast, valideret format. Kamerafotos rettes
   automatisk for rotation og skaleres, før de sendes.
3. **Kontrol og bogføring** – du ser dokumentet ved siden af de aflæste felter, retter evt. og trykker
   *Bogfør*. Programmet danner en balanceret postering (fx omkostning + købsmoms / bank) og viser
   forslaget, før du bogfører. Beløb i fremmed valuta skal omregnes til DKK først (der er en
   omregningsfunktion med plads til kurs og kilde).
4. **Momsregnskab** – *Moms* viser momsangivelsens felter (salgsmoms, moms af varekøb i udlandet,
   moms af ydelseskøb i udlandet, købsmoms, momstilsvar) og rubrik A/B/C for den valgte periode
   (måned, kvartal eller halvår). Når du har indberettet på skat.dk, markerer du perioden som
   afregnet: momskontiene nulstilles over på momsafregningskontoen, og perioden låses.
5. **Rapporter** – resultatopgørelse, balance og kontokort.
6. **Eksport & backup** – SAF-T (XML), CSV, sikkerhedskopi (zip med database + alle bilag),
   periodelåse og kontrolspor.

Fejl rettes aldrig ved at slette eller redigere – bogførte posteringer tilbageføres (storno) med en
modpostering, som henviser til den oprindelige.

## Momskoder

| Kode | Anvendelse | Bogføring |
|------|------------|-----------|
| K25 | Dansk køb med 25 % moms | Netto på omkostningskonto, moms på 5610 Købsmoms |
| K25R | Restaurationsbesøg (25 % af momsen kan fradrages) | Fradragsberettiget del på 5610, resten på omkostningskontoen |
| K25H | Delvis erhvervsmæssig anvendelse (50 % fradrag) | Som K25R med 50 % |
| K0 | Køb uden moms (forsikring, gebyrer, porto, offentlig transport) | Hele beløbet på omkostningskontoen |
| KEUV / KEUY | Varer / ydelser købt i EU uden moms (omvendt betalingspligt) | 25 % beregnes: kredit 6220, debet 5610; grundlag i rubrik A |
| K3V / K3Y | Varer / ydelser købt uden for EU | Som KEUV/KEUY, angives i "moms af vare-/ydelseskøb i udlandet" |
| S25 | Dansk salg med 25 % moms | Netto på omsætningskonto, moms på 6210 Salgsmoms |
| S0 | Momsfrit salg (momslovens § 13) | Hele beløbet på omsætningskonto |
| SEUV / SEUY | Salg af varer / ydelser til EU-virksomheder | Uden moms; grundlag i rubrik B |
| S3 | Salg til lande uden for EU | Uden moms; grundlag i rubrik C |
| INGEN | Balanceposteringer, private hævninger m.m. | Indgår ikke i momsregnskabet |

Brug K0 på konto 3315 til udgifter til personbil (intet momsfradrag) og konto 3320 med kode INGEN
til kørselsgodtgørelse efter statens takster.

## Opbygning

```
app/
  main.py        webapplikation (FastAPI) – alle sider og formularer
  models.py      datamodel (SQLite via SQLAlchemy); alle beløb i øre
  kontoplan.py   standardkontoplan og momskoder
  bookkeeping.py posteringer, storno, hash-kæde, periodelåse, momsafregning, rapporter
  vat.py         momsberegning og momsangivelse
  extraction.py  aflæsning af bilag med Claude (struktureret output)
  files.py       opbevaring af originalbilag, billedbehandling af kamerafotos
  saft.py        SAF-T-eksport
  backup.py      sikkerhedskopi (kan køres fra cron: python -m app.backup)
  templates/     HTML-sider (Jinja2), static/ CSS og lidt JavaScript
tests/           pytest – bogføring, moms, aflæsning (simuleret), hele webflowet
data/            oprettes automatisk: regnskab.db, bilag/, backup/  (ikke i git)
```

## Bogføringsloven – hvad programmet gør, og hvad du selv skal gøre

| Krav | Hvor i loven | Programmet |
|------|--------------|------------|
| Alle transaktioner registreres nøjagtigt, snarest muligt og i rækkefølge | § 7 | Fortløbende posteringsnumre, registreringstidspunkt gemmes, posteringer skal balancere |
| Transaktionsspor og kontrolspor | § 4, § 8 | Hver postering henviser til sit bilag og omvendt; alle handlinger logges i kontrolsporet |
| Rettelser må ikke skjule det oprindelige indhold | § 8 | Posteringer kan ikke ændres eller slettes – kun tilbageføres; hash-kæde afslører manipulation |
| Bilag skal dokumentere registreringerne (dato, beløb, udsteder, modtager, moms) | § 9 | Originalfilen gemmes uændret med kontrolsum; felterne aflæses og gemmes |
| Opbevaring i 5 år fra regnskabsårets udløb | § 12 | Bilag og database ligger i `data/`; annullerede bilag slettes aldrig |
| Digital opbevaring og sikkerhedskopi | §§ 13, 16 | Zip-backup med alt materiale – **du skal selv gemme kopien hos en tredjepart (cloud) regelmæssigt**, fx med et cron-job der kører `python -m app.backup` og synkroniserer `data/backup/` |
| SAF-T-eksport til myndighederne | § 16 | *Eksport & backup → Hent SAF-T*. Filen følger strukturen i dansk SAF-T Financial (OECD 2.0); validér mod Erhvervsstyrelsens aktuelle XSD, før den afleveres |
| Standardkontoplan | § 16 / bekendtgørelse om digitale bogføringssystemer | Feltet *Standardkonto* på hver konto bruges til at mappe til Erhvervsstyrelsens standardkontoplan; udfyld det (evt. sammen med din revisor) |
| Momsregnskab | Momsloven / momsbekendtgørelsen | Momsangivelsens felter og rubrikker beregnes fra momskoderne; periodeafregning låser perioden |

Bemærk:

* Dette er et **eget (ikke-registreret) bogføringssystem**. Kravene til de digitale systemer, som
  virksomheder selv udvikler, står i bekendtgørelsen om ikke-registrerede bogføringssystemer.
  Programmet understøtter registrering, opbevaring, backup-eksport, SAF-T og standardkontoplan, men
  **automatisk bankafstemning og afsendelse/modtagelse af e-fakturaer (NemHandel/Peppol) er ikke
  indbygget**. Bankafstemning gøres manuelt via kontokortet for bankkontoen.
* Programmet erstatter ikke rådgivning – få din revisor til at gennemgå kontoplanen, momskoderne og
  den første momsangivelse.
* Programmet er uden login og er beregnet til at køre lokalt eller bag en beskyttet forbindelse.
  Sæt det aldrig direkte på internettet uden adgangskontrol (reverse proxy med login/HTTPS).
