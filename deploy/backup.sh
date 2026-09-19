#!/usr/bin/env bash
# Nightly backup. The entire business is one SQLite file.
#   0 3 * * * /opt/answerrank/deploy/backup.sh
set -euo pipefail

DB="${ANSWERRANK_DB:-/opt/answerrank/data/answerrank.db}"
DEST="${BACKUP_DIR:-/opt/answerrank/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$DEST"
STAMP="$(date +%F-%H%M)"
OUT="$DEST/answerrank-$STAMP.db"

# .backup is safe on a live database; cp is not.
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"

find "$DEST" -name 'answerrank-*.db.gz' -mtime "+$KEEP_DAYS" -delete

echo "backed up to $OUT.gz"
echo "restore with: gunzip -c $OUT.gz > restored.db"
