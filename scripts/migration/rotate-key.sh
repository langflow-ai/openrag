#!/usr/bin/env bash
# Run with Bash. This wrapper prepares SQLite restores; it never switches a deployment.
set +x
set -euo pipefail
umask 077

log() {
  local label=$1 color=$2 message=$3
  if [[ -t 2 && -z ${NO_COLOR:-} && ${TERM:-dumb} != dumb ]]; then
    printf '\033[%sm[%s]\033[0m %s\n' "$color" "$label" "$message" >&2
  else
    printf '[%s] %s\n' "$label" "$message" >&2
  fi
}

step() { log STEP '1;36' "$1"; }
done_step() { log OK '1;32' "$1"; }
fail() { log ERROR '1;31' "$1"; exit 1; }
if [[ ${1:-} != check || -n ${MIGRATION_DIR:-} ]]; then
  : "${MIGRATION_DIR:?Set MIGRATION_DIR to an absolute path under a private parent directory}"
  [[ "$MIGRATION_DIR" = /* ]] || fail 'MIGRATION_DIR must be absolute.'
  [[ ! -L "$MIGRATION_DIR" ]] || fail 'MIGRATION_DIR cannot be a symlink.'
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
backup="${MIGRATION_DIR:-}/backup"
restore="${MIGRATION_DIR:-}/restore"
keys="${MIGRATION_DIR:-}/keys"

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
    step 'Checking source directories and backup destination.'
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
    step 'Creating private backup and restore directories.'
    mkdir -m 700 -- "$MIGRATION_DIR" || fail 'Choose a new migration directory; nothing was overwritten.'
    mkdir -p -- "$backup/data" "$backup/config" "$restore"
    step 'Copying data and config files into the backup.'
    rsync -rt --exclude='/openrag.db' --exclude='/openrag.db-wal' \
      --exclude='/openrag.db-shm' --exclude='/openrag.db-journal' -- "$data/" "$backup/data/"
    rsync -rt -- "$config/" "$backup/config/"
    # Read-only source; the backup API writes a consistent DB without copying sidecars.
    step 'Backing up SQLite using the read-only source connection.'
    python3 - "$data/openrag.db" "$backup/data/openrag.db" <<'PY'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

with closing(sqlite3.connect(Path(sys.argv[1]).as_uri() + '?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(sys.argv[2])) as target:
        source.backup(target)
PY
    step 'Making a separate working restore from the backup.'
    cp -R -- "$backup/data" "$backup/config" "$restore/"
    done_step 'Backup and working restore created.'
    ;;
  keys)
    [[ -d "$restore/data" && -d "$restore/config" ]] || fail 'Run backup first.'
    step 'Reading both keys without echoing their values.'
    read -r -s -p 'Paste the current OPENRAG_ENCRYPTION_KEY: ' old_key
    printf '\n' >&2
    [[ -n "$old_key" ]] || fail 'The old key cannot be empty.'
    read -r -s -p 'Paste the replacement OPENRAG_ENCRYPTION_KEY: ' new_key
    printf '\n' >&2
    [[ -n "$new_key" ]] || fail 'The replacement key cannot be empty.'
    [[ "$old_key" != "$new_key" ]] || fail 'The old and replacement keys must differ.'
    step 'Writing both keys to protected files.'
    mkdir -m 700 -- "$keys" || fail 'Key directory already exists; nothing was overwritten.'
    printf '%s\n' "$old_key" > "$keys/old"
    printf '%s\n' "$new_key" > "$keys/new"
    unset old_key new_key
    done_step 'Both key files saved.'
    ;;
  dry-run)
    step 'Checking the restored copy with the old key (read-only).'
    rotate check --old-key-file "$keys/old"
    done_step 'Dry run finished. Review the ciphertext counts before applying.'
    ;;
  check)
    shift
    data=${OLD_DATA_DIR:-}
    config=${OLD_CONFIG_DIR:-}
    key_file=''
    prompt_key=false
    while (($#)); do
      case "$1" in
        --data-dir|--config-dir|--key-file)
          [[ -n ${2:-} && "$2" != --* ]] || fail "Missing value for $1."
          case "$1" in
            --data-dir) data=$2 ;;
            --config-dir) config=$2 ;;
            --key-file) key_file=$2 ;;
          esac
          shift 2
          ;;
        --prompt-key) prompt_key=true; shift ;;
        *) fail 'Usage: bash rotate-key.sh check [--data-dir PATH] [--config-dir PATH] [--key-file PATH | --prompt-key]' ;;
      esac
    done
    [[ -n "$data" && -n "$config" ]] ||
      fail 'Set OLD_DATA_DIR and OLD_CONFIG_DIR or pass --data-dir and --config-dir.'
    [[ "$prompt_key" = false || -z "$key_file" ]] || fail 'Choose --key-file or --prompt-key.'
    if [[ "$prompt_key" = false && -z "$key_file" && -n ${MIGRATION_DIR:-} && -f "$keys/new" ]]; then
      key_file="$keys/new"
    fi
    command=(
      env -u OPENRAG_ENCRYPTION_KEY "${MIGRATION_PYTHON:-python3}"
      "$script_dir/rotate_encryption_key.py" verify
      --data-dir "$data" --config-dir "$config" --sqlite "$data/openrag.db"
      --source-data-dir "${OLD_DATA_PATH_AS_STORED:-data}"
      --tenant-id "${OPENRAG_TENANT_ID:-openrag}"
    )
    step 'Checking stored ciphertext read-only. Keep OpenRAG writers stopped.'
    if [[ -n "$key_file" ]]; then
      step 'Using the supplied or saved key file.'
      "${command[@]}" --key-file "$key_file"
    else
      IFS= read -r -s -p 'Paste the OPENRAG_ENCRYPTION_KEY to check: ' check_key ||
        fail 'No key read. Use --key-file for non-interactive checks.'
      printf '\n' >&2
      printf '%s\n' "$check_key" | "${command[@]}" --key-file /dev/stdin
      unset check_key
    fi
    done_step 'The supplied key authenticated the stored ciphertext.'
    ;;
  apply)
    step 'Rotating the restored copy only. The backup is not modified.'
    [[ -d "$restore" && ! -L "$restore" ]] || fail 'Restore must be an existing non-symlink directory.'
    rotate apply-to-copy --old-key-file "$keys/old" \
      --original-data-dir "${OLD_DATA_DIR:?Set OLD_DATA_DIR to the original data path}" \
      --original-config-dir "${OLD_CONFIG_DIR:?Set OLD_CONFIG_DIR to the original config path}"
    step 'Verifying the restored copy with only the replacement key.'
    rotate verify
    step 'Recording hashes of the verified working copy for cutover.'
    "${MIGRATION_PYTHON:-python3}" "$script_dir/cutover_data.py" \
      "$MIGRATION_DIR" --record-verified-restore
    done_step 'Rotation verified. No deployment was switched.'
    ;;
  cutover-data)
    case $# in
      1)
        set -- "$1" "${OLD_DATA_DIR:?Set OLD_DATA_DIR or pass both runtime paths}" \
          "${OLD_CONFIG_DIR:?Set OLD_CONFIG_DIR or pass both runtime paths}"
        ;;
      3)
        [[ "$2" = /* && "$3" = /* ]] || fail 'Pass two absolute paths or both named flags.'
        ;;
      5)
        case "$2:$4" in
          --original-data-dir:--original-config-dir) set -- "$1" "$3" "$5" ;;
          --original-config-dir:--original-data-dir) set -- "$1" "$5" "$3" ;;
          *) fail 'Pass both --original-data-dir and --original-config-dir.' ;;
        esac
        ;;
      *) fail 'Usage: bash rotate-key.sh cutover-data [--original-data-dir PATH --original-config-dir PATH]' ;;
    esac
    step 'Preparing data-only cutover. No keys or services will be changed.'
    env -u OPENRAG_ENCRYPTION_KEY "${MIGRATION_PYTHON:-python3}" \
      "$script_dir/cutover_data.py" "$MIGRATION_DIR" "$2" "$3"
    done_step 'Data cutover complete. Set the replacement key before starting OpenRAG.'
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
    log WARNING '1;33' "$warning"
    printf 'Remove %s? Type %s to confirm: ' "$(cd -- "$target" && pwd -P)" "$2" >&2
    read -r confirmation
    [[ "$confirmation" = "$2" ]] || fail 'Cleanup cancelled.'
    step "Removing the selected $2 directory."
    rm -r -- "$target"
    done_step "Removed the selected $2 directory."
    ;;
  *) fail 'Usage: bash rotate-key.sh {backup|keys|dry-run|check|apply|cutover-data|cleanup}' ;;
esac
