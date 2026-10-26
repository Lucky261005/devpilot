#!/usr/bin/env bash
# Back up the Docker Compose deployment: PostgreSQL dump + snapshots archive (docs/backup-restore.md).
# Usage: scripts/backup.sh <backup-dir>
# Writes devpilot-<stamp>.dump and devpilot-data-<stamp>.tar.gz only when BOTH succeed; a failed run
# leaves no file with a final name. Never deletes old backups. No password is passed anywhere:
# pg_dump uses the db container's local socket.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep /data a container path

dest=${1:?usage: scripts/backup.sh <backup-dir>}
cd "$(dirname "$0")/.." # the repository root, where docker-compose.yml is
mkdir -p "$dest"
stamp=$(date +%Y%m%d-%H%M%S)
db="$dest/devpilot-$stamp.dump"
data="$dest/devpilot-data-$stamp.tar.gz"
trap 'rm -f "$db.partial" "$data.partial"' EXIT

docker compose exec -T db pg_dump -U devpilot -d devpilot -Fc >"$db.partial"
docker compose exec -T backend tar -czf - -C /data . >"$data.partial"
mv "$db.partial" "$db"
mv "$data.partial" "$data"
echo "backup written: $db ($(wc -c <"$db") bytes), $data ($(wc -c <"$data") bytes)"
