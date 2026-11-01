#!/usr/bin/env bash
# Dump the Postgres database to backups/db-YYYY-MM-DD.sql.gz and keep the last 14 days.
# Run daily from cron on the server, e.g.:
#   0 4 * * * /root/app/scripts/backup-db.sh >> /root/app/backups/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

file="backups/db-$(date +%F).sql.gz"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$file.tmp"
mv "$file.tmp" "$file"

find backups -name 'db-*.sql.gz' -mtime +14 -delete
