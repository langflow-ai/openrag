#!/usr/bin/env bash
# Run with Bash. This wrapper prepares SQLite restores; it never switches a deployment.
set +x
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
: "${MIGRATION_DIR:?Set MIGRATION_DIR to an absolute path under a private parent directory}"
[[ "$MIGRATION_DIR" = /* ]] || fail 'MIGRATION_DIR must be absolute.'
[[ ! -L "$MIGRATION_DIR" ]] || fail 'MIGRATION_DIR cannot be a symlink.'

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
backup="$MIGRATION_DIR/backup"
restore="$MIGRATION_DIR/restore"
keys="$MIGRATION_DIR/keys"

rotate() {
  env -u OPENRAG_ENCRYPTION_KEY \
    "${MIGRATION_PYTHON:-python3}" "$script_dir/rotate_encryption_key.py" "$@" \
    --data-dir "$restore/data" --config-dir "$restore/config" \
    --sqlite "$restore/data/openrag.db" \
    --source-data-dir "${OLD_DATA_PATH_AS_STORED:-data}" \
    --tenant-id "${OPENRAG_TENANT_ID:-openrag}" --new-key-file "$keys/new"
}

case ${1:-} in
  backup)
    : "${OLD_DATA_DIR:?Set OLD_DATA_DIR to the existing data directory}"
    : "${OLD_CONFIG_DIR:?Set OLD_CONFIG_DIR to the existing config directory}"
    data=$(cd -- "$OLD_DATA_DIR" && pwd -P)
    config=$(cd -- "$OLD_CONFIG_DIR" && pwd -P)
    parent=$(cd -- "$(dirname -- "$MIGRATION_DIR")" && pwd -P)
    for source in "$data" "$config"; do
      case "$parent/" in "$source/"*) fail 'Migration destination must be outside the source directories.' ;; esac
      [[ -z $(find "$source" ! -type d ! -type f -print -quit) ]] ||
        fail 'Source contains symlinks or special files. Prepare an isolated restore manually.'
    done
    [[ -f "$data/openrag.db" ]] || fail 'Expected SQLite database at OLD_DATA_DIR/openrag.db.'
    mkdir -m 700 -- "$MIGRATION_DIR" || fail 'Choose a new migration directory; nothing was overwritten.'
    mkdir -p -- "$backup/data" "$backup/config" "$restore"
    rsync -rt --exclude='/openrag.db' --exclude='/openrag.db-wal' \
      --exclude='/openrag.db-shm' --exclude='/openrag.db-journal' -- "$data/" "$backup/data/"
    rsync -rt -- "$config/" "$backup/config/"
    # Read-only source; the backup API writes a consistent DB without copying sidecars.
    python3 - "$data/openrag.db" "$backup/data/openrag.db" <<'PY'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

with closing(sqlite3.connect(Path(sys.argv[1]).as_uri() + '?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(sys.argv[2])) as target:
        source.backup(target)
PY
    cp -R -- "$backup/data" "$backup/config" "$restore/"
    printf '%s\n' 'Backup and independent working restore created.'
    ;;
  keys)
    [[ -d "$restore/data" && -d "$restore/config" ]] || fail 'Run backup first.'
    read -r -s -p 'Paste the current OPENRAG_ENCRYPTION_KEY: ' old_key
    printf '\n' >&2
    [[ -n "$old_key" ]] || fail 'The old key cannot be empty.'
    read -r -s -p 'Paste the replacement OPENRAG_ENCRYPTION_KEY: ' new_key
    printf '\n' >&2
    [[ -n "$new_key" ]] || fail 'The replacement key cannot be empty.'
    [[ "$old_key" != "$new_key" ]] || fail 'The old and replacement keys must differ.'
    mkdir -m 700 -- "$keys" || fail 'Key directory already exists; nothing was overwritten.'
    printf '%s\n' "$old_key" > "$keys/old"
    printf '%s\n' "$new_key" > "$keys/new"
    unset old_key new_key
    printf '%s\n' 'Old and replacement key files saved.'
    ;;
  dry-run) rotate check --old-key-file "$keys/old" ;;
  apply)
    rotate apply-to-copy --old-key-file "$keys/old"
    rotate verify
    ;;
  cleanup)
    [[ $# = 2 ]] || fail 'Usage: bash rotate-key.sh cleanup {keys|restore|backup}'
    case "$2" in
      keys) target=$keys; warning='Save both keys in your secret manager first.' ;;
      restore) target=$restore; warning='Do not remove a restore that a deployment uses.' ;;
      backup) target=$backup; warning='Keep the backup until the rollback window closes.' ;;
      *) fail 'Cleanup target must be keys, restore, or backup.' ;;
    esac
    [[ -d "$target" && ! -L "$target" ]] || fail 'Cleanup target must be an existing non-symlink directory.'
    [[ -t 0 ]] || fail 'Cleanup requires an interactive terminal.'
    printf '%s\n' "$warning" >&2
    printf 'Remove %s? Type %s to confirm: ' "$(cd -- "$target" && pwd -P)" "$2" >&2
    read -r confirmation
    [[ "$confirmation" = "$2" ]] || fail 'Cleanup cancelled.'
    rm -r -- "$target"
    ;;
  *) fail 'Usage: bash rotate-key.sh {backup|keys|dry-run|apply|cleanup}' ;;
esac
