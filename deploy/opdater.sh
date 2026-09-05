#!/bin/sh
# Henter nyeste version fra GitHub og genstarter programmet uden at data røres.
set -e
cd "$(dirname "$0")/.."
git pull
# Variabler fra .env (bl.a. PROXY_NETWORK) gøres tilgængelige for docker compose
if [ -f .env ]; then set -a; . ./.env; set +a; fi
if [ -n "${PROXY_NETWORK:-}" ]; then
  export COMPOSE_FILE=deploy/docker-compose.bag-proxy.yml
fi
docker compose build app backup
docker compose up -d
docker image prune -f >/dev/null
echo "Opdateret."
