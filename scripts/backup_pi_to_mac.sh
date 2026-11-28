#!/usr/bin/env bash
# Frequent automated backup from Raspberry Pi (lipi@192.168.1.13) to Mac Mini.
# Syncs:
#   1. PostgreSQL nightly/periodic dumps (/var/backups/postgres/ -> ~/Backups/rpi-postgres/)
#   2. Live JSON snapshots of books & correction_memory from Pi localhost API (captures mid-day edits)
#   3. Workspace originals (source PDFs), training_crops, and exports (-> ~/Backups/telugu-digitizer/workspace/)
#
# Passwordless by design: relies on SSH key auth and Pi's `pgbackup` group permissions (no sudo required).

set -euo pipefail

PI_HOST="${PI_HOST:-lipi@192.168.1.13}"
PI_WORKSPACE="${PI_WORKSPACE:-/home/lipi/telugu-digitizer/workspace}"
PI_PG_DIR="${PI_PG_DIR:-/var/backups/postgres}"
PI_LOCAL_API="${PI_LOCAL_API:-http://127.0.0.1:8085}"
PG_BACKUP_DEST="${PG_BACKUP_DEST:-$HOME/Backups/rpi-postgres}"
APP_BACKUP_DEST="${APP_BACKUP_DEST:-$HOME/Backups/telugu-digitizer}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
INCLUDE_PAGE_IMAGES="${INCLUDE_PAGE_IMAGES:-0}"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o StrictHostKeyChecking=accept-new)
LOG_FILE="$APP_BACKUP_DEST/backup.log"

mkdir -p "$PG_BACKUP_DEST" "$APP_BACKUP_DEST/snapshots" "$APP_BACKUP_DEST/workspace"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

log "Starting Pi -> Mac Mini backup from $PI_HOST"

if ! ssh "${SSH_OPTS[@]}" "$PI_HOST" true 2>/dev/null; then
  log "WARN: $PI_HOST is unreachable via passwordless SSH; skipping this run."
  exit 0
fi

# 1. Sync PostgreSQL custom dumps from /var/backups/postgres/
log "Syncing PostgreSQL dumps from $PI_HOST:$PI_PG_DIR -> $PG_BACKUP_DEST"
rsync -az --partial -e "ssh ${SSH_OPTS[*]}" \
  "$PI_HOST:$PI_PG_DIR/" "$PG_BACKUP_DEST/" >>"$LOG_FILE" 2>&1

LATEST_DUMP="$(find "$PG_BACKUP_DEST" -maxdepth 1 -type f -name 'telugu_digitizer_*.dump' -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -n 1 || true)"
if [[ -n "$LATEST_DUMP" && -s "$LATEST_DUMP" ]]; then
  DUMP_SIZE="$(stat -f%z "$LATEST_DUMP" 2>/dev/null || wc -c < "$LATEST_DUMP")"
  log "OK: Latest telugu_digitizer dump: $(basename "$LATEST_DUMP") (${DUMP_SIZE} bytes)"
else
  log "WARN: No telugu_digitizer_*.dump found yet in $PG_BACKUP_DEST"
fi

# 2. Capture live mid-day JSON snapshot of books & correction_memory via Pi localhost API
STAMP="$(date '+%Y%m%d_%H%M%S')"
SNAP_DIR="$APP_BACKUP_DEST/snapshots/$STAMP"
mkdir -p "$SNAP_DIR"

if ssh "${SSH_OPTS[@]}" "$PI_HOST" "curl -fsS '$PI_LOCAL_API/api/v1/corrections'" > "$SNAP_DIR/correction_memory.json" 2>/dev/null; then
  CORR_BYTES="$(wc -c < "$SNAP_DIR/correction_memory.json" | tr -d ' ')"
  log "OK: Saved live correction_memory.json (${CORR_BYTES} bytes)"
else
  rm -f "$SNAP_DIR/correction_memory.json"
  log "WARN: Could not fetch live /api/v1/corrections from $PI_LOCAL_API"
fi

if ssh "${SSH_OPTS[@]}" "$PI_HOST" "curl -fsS '$PI_LOCAL_API/api/v1/books'" > "$SNAP_DIR/books.json" 2>/dev/null; then
  BOOKS_BYTES="$(wc -c < "$SNAP_DIR/books.json" | tr -d ' ')"
  log "OK: Saved live books.json (${BOOKS_BYTES} bytes)"
else
  rm -f "$SNAP_DIR/books.json"
  log "WARN: Could not fetch live /api/v1/books from $PI_LOCAL_API"
fi

ln -sfn "$SNAP_DIR" "$APP_BACKUP_DEST/snapshots/latest"

# 3. Sync source PDFs, training crops, and exports (skip regenerable page PNGs by default)
RSYNC_EXCLUDES=(--exclude='pages/' --exclude='tmp/' --exclude='*.lock')
if [[ "$INCLUDE_PAGE_IMAGES" == "1" ]]; then
  RSYNC_EXCLUDES=(--exclude='tmp/' --exclude='*.lock')
fi

log "Syncing workspace artifacts ($PI_WORKSPACE -> $APP_BACKUP_DEST/workspace)"
rsync -az --partial "${RSYNC_EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" \
  "$PI_HOST:$PI_WORKSPACE/" "$APP_BACKUP_DEST/workspace/" >>"$LOG_FILE" 2>&1

# 4. Prune old JSON snapshots beyond RETENTION_DAYS (keep PostgreSQL dumps up to RETENTION_DAYS as well)
find "$APP_BACKUP_DEST/snapshots" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true
find "$PG_BACKUP_DEST" -maxdepth 1 -type f -name '*.dump' -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true

log "Backup completed successfully."
