# Sæt regnskabsprogrammet på en server

Med denne opsætning kører programmet døgnet rundt på en lille server, og brugerne logger ind fra
en browser på pc, tablet eller telefon. Alt kører i Docker: programmet, en natlig backup og én fælles
Caddy (mappen `proxy/`), som sørger for HTTPS-certifikater og fordeler trafikken, så flere apps
(fx regnskab og golfturneringen i `golf/`) kan dele samme server.

Det tager 30 til 45 minutter første gang. Du skal bruge:

* en konto hos en serverudbyder (vejledningen bruger Hetzner, som har servere i EU),
* din `ANTHROPIC_API_KEY`,
* eventuelt et domæne (fx `regnskab.innermind.dk`). Uden domæne kan du bruge serverens IP via
  sslip.io, se trin 4.

## 1. Opret serveren

1. Opret en konto på <https://www.hetzner.com/cloud> og et nyt projekt.
2. Tryk *Add Server*: placering **Falkenstein** eller **Helsinki** (EU), image **Ubuntu 24.04**,
   type **CX22** (2 vCPU, 4 GB, rigeligt), netværk: både IPv4 og IPv6.
3. Under *SSH keys*: tilføj din offentlige SSH-nøgle. Har du ingen, kan du i stedet få en adgangskode
   pr. e-mail, men SSH-nøgle er mere sikkert. På Windows laver du en nøgle med `ssh-keygen` i
   PowerShell og indsætter indholdet af `C:\Users\<dig>\.ssh\id_ed25519.pub`.
4. Slå **Backups** til (koster 20 % oven i serverprisen). Hetzner tager så en daglig kopi af hele
   serveren, som ligger hos en uafhængig part i EU. Det opfylder bogføringslovens krav om
   sikkerhedskopi hos tredjepart.
5. Tryk *Create & Buy now*. Notér serverens IPv4-adresse, fx `65.108.1.2`.

## 2. Log ind og installér Docker

Fra PowerShell eller Terminal:

```bash
ssh root@65.108.1.2
```

På serveren:

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
```

## 3. Hent programmet

```bash
cd /opt
git clone https://github.com/erikjul/innermind_regnskab.git
cd innermind_regnskab
cp .env.example .env
nano .env
```

Udfyld i `.env`:

* `ANTHROPIC_API_KEY` – din nøgle.
* `REGNSKAB_SESSION_SECRET` – en lang tilfældig tekst. Lav den med `openssl rand -base64 48` og
  indsæt resultatet.

Gem med Ctrl+O, Enter, og luk med Ctrl+X.

## 4. Vælg adresser og start den fælles Caddy

Alle apps på serveren deler én Caddy, som bor i mappen `proxy/`. Den får en adresse pr. app:

```bash
cd /opt/innermind_regnskab/proxy
cp .env.example .env
nano .env
```

**Med eget domæne:** log ind hos din domæneudbyder (fx Simply, One.com, DanDomain) og opret en
*A-record* pr. app (fx `regnskab` og `golf`), der peger på serverens IPv4-adresse. Skriv så
`REGNSKAB_DOMAENE=regnskab.innermind.dk` og `GOLF_DOMAENE=golf.innermind.dk`. Det kan tage op til
en time, før DNS virker.

**Uden domæne:** brug sslip.io, som oversætter en IP-adresse til et navn, Caddy kan få certifikat
til. Skriv IP-adressen med bindestreger og et præfiks pr. app: `REGNSKAB_DOMAENE=regnskab.65-108-1-2.sslip.io`
og `GOLF_DOMAENE=golf.65-108-1-2.sslip.io`. Det virker med det samme og kan senere skiftes til
rigtige domæner. Begge linjer skal være udfyldt, også hvis du kun bruger den ene app.

Opret det fælles netværk og start Caddy (kun første gang):

```bash
docker network create web
docker compose up -d
```

## 5. Start regnskabsprogrammet

```bash
cd /opt/innermind_regnskab
docker compose up -d --build
docker compose logs -f app
```

Når der står "Application startup complete", åbner du adressen i browseren
(`https://regnskab.innermind.dk` eller `https://regnskab.65-108-1-2.sslip.io`). Første gang ser du siden
*Opret administrator*. Opret dig selv som administrator, og opret derefter din hustru under
*Brugere* i topmenuen. Tryk Ctrl+C for at forlade loggen (programmet kører videre).

## 6. Flyt data fra din pc (hvis du er begyndt lokalt)

På pc'en: *Eksport & backup → Download sikkerhedskopi*. Zippen indeholder `regnskab.db` og
mappen `bilag`. Kopiér den til serveren og pak den ud i datavolumen:

```bash
# fra din pc
scp regnskab_backup_2026-09-04.zip root@65.108.1.2:/tmp/
# på serveren
docker compose stop app backup
docker run --rm -v innermind_regnskab_regnskab_data:/data -v /tmp:/tmp python:3.12-slim \
  sh -c "cd /data && rm -rf regnskab.db bilag && python -m zipfile -e /tmp/regnskab_backup_2026-09-04.zip . && chown -R 10001:10001 /data"
docker compose start app backup
```

Brugerne oprettes igen på serveren (de indgår i databasen fra pc'en, hvis du nåede at oprette dem
der; ellers kommer siden *Opret administrator* frem).

## 7. Drift

* **Opdatere programmet:** `cd /opt/innermind_regnskab && ./deploy/opdater.sh`
* **Flere apps:** hver app har sin egen `docker-compose.yml`, der kobler sig på netværket `web`
  med et alias (fx `golf`). Tilføj en blok i `proxy/Caddyfile` og en adresse i `proxy/.env`, og
  genstart Caddy med `cd proxy && docker compose up -d`. Golfturneringen er beskrevet i `golf/README.md`.
* **Se log:** `docker compose logs --tail 100 app`
* **Genstart:** `docker compose restart`
* **Backup:** containeren `backup` laver en zip hver nat i volumen `regnskab_backup` og beholder de
  seneste 30. Hetzners serverbackup dækker tredjepartskravet. Vil du også have kopier i din egen
  cloud-mappe (OneDrive, Google Drive, Dropbox), så installér `rclone`, kør `rclone config`, og sæt
  `deploy/rclone-backup.sh` i cron (der står en vejledning i filen).
* **Hent en backup ned til dig selv:** *Eksport & backup → Download sikkerhedskopi* i browseren.
  Gør det mindst ved hvert årsskifte, og gem zippen i 5 år.
* **Sikkerhedsopdateringer af serveren:** `apt update && apt upgrade -y` en gang om måneden, eller
  slå automatiske opdateringer til med `apt install unattended-upgrades`.
* **Glemt adgangskode:** `docker compose exec app python -m app.users kodeord <brugernavn>`.

## Sikkerhed, kort

* Alt går over HTTPS, og login-cookien sendes kun krypteret.
* Efter 8 forkerte logins fra samme adresse spærres der i 15 minutter.
* Programmet kører som en almindelig bruger i containeren, ikke som root.
* Kun portene 22, 80 og 443 er åbne i firewallen. Overvej at begrænse port 22 til din egen IP i
  Hetzners firewall, når alt kører.
* Brug lange adgangskoder (mindst 10 tegn, gerne en sætning), og giv kun administratorrollen til
  den, der skal oprette brugere.
