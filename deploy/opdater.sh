#!/bin/sh
# Henter nyeste version fra GitHub og genstarter programmet uden at data røres.
set -e
cd "$(dirname "$0")/.."
git pull
docker compose build app backup
docker compose up -d
docker image prune -f >/dev/null
echo "Opdateret."
