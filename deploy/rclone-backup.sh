#!/bin/sh
# Kopierer sikkerhedskopierne til en cloud-tjeneste med rclone (bogføringslovens krav om kopi hos tredjepart).
# Opsætning én gang:  rclone config   (opret fx en remote ved navn "cloud" til OneDrive, Google Drive eller Dropbox)
# Kør dagligt fra cron:  0 4 * * * /opt/innermind_regnskab/deploy/rclone-backup.sh
set -e
KILDE=$(docker volume inspect innermind_regnskab_regnskab_backup -f '{{ .Mountpoint }}')
rclone copy "$KILDE" cloud:InnerMind-regnskab-backup --min-age 1m
