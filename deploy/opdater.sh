#!/bin/sh
# Henter nyeste version fra GitHub og genstarter programmet uden at data røres.
set -e
cd "$(dirname "$0")/.."
git pull
if [ -n "$COMPOSE_FILE" ]; then :; elif docker ps --format "{{.Names}}" | grep -q "^innermind-regnskab$"; then export COMPOSE_FILE=deploy/docker-compose.bag-proxy.yml; fi
docker compose build app backup
docker compose up -d
docker image prune -f >/dev/null
echo "Opdateret."
