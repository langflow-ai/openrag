#!/usr/bin/env bash
# File-scoped SQLite rotation. Does not update deployment keys or start services.
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
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ ${1:-} = files ]]; then
  shift
  exec env -u OPENRAG_ENCRYPTION_KEY "${MIGRATION_PYTHON:-python3}" \
    "$script_dir/rotate_files.py" "$@"
fi

case ${1:-}:${2:-} in
  cleanup:keys) ;;
  *) fail 'Usage: bash rotate-key.sh files {backup|dry-run|apply|check|cutover}, or cleanup keys. Use bash prepare.sh to enter keys.' ;;
esac
: "${MIGRATION_DIR:?Set MIGRATION_DIR to a private directory for keys}"
[[ "$MIGRATION_DIR" = /* && -d "$MIGRATION_DIR" && ! -L "$MIGRATION_DIR" ]] ||
  fail 'MIGRATION_DIR must be an existing absolute directory, not a symlink.'
keys="$MIGRATION_DIR/keys"

case ${1:-} in
  cleanup)
    [[ $# = 2 && "$2" = keys ]] || fail 'Usage: bash rotate-key.sh cleanup keys'
    target=$keys
    [[ -d "$target" && ! -L "$target" ]] || fail 'Cleanup target must be an existing non-symlink directory.'
    [[ -t 0 ]] || fail 'Cleanup requires an interactive terminal.'
    log WARNING '1;33' 'Save both keys in your secret manager first.'
    printf 'Remove %s? Type %s to confirm: ' "$(cd -- "$target" && pwd -P)" "$2" >&2
    read -r confirmation
    [[ "$confirmation" = "$2" ]] || fail 'Cleanup cancelled.'
    step "Removing the selected $2 directory."
    rm -r -- "$target"
    done_step "Removed the selected $2 directory."
    ;;
esac
