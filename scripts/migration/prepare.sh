#!/usr/bin/env bash
# Prepare key files only. Does not back up or modify application data.
set +x
set -euo pipefail
umask 077

fail() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }
[[ $# = 0 ]] || fail 'Usage: bash prepare.sh'
: "${MIGRATION_DIR:?Export MIGRATION_DIR to a private workspace path first}"
[[ "$MIGRATION_DIR" = /* && ! -L "$MIGRATION_DIR" ]] ||
  fail 'MIGRATION_DIR must be an absolute path, not a symlink.'
keys="$MIGRATION_DIR/keys"
[[ ! -e "$keys" && ! -L "$keys" ]] || fail 'Key directory already exists; nothing was overwritten.'

printf '[STEP] Reading both keys without echoing their values.\n' >&2
IFS= read -r -s -p 'Paste the current OPENRAG_ENCRYPTION_KEY: ' old_key
printf '\n' >&2
[[ -n "$old_key" ]] || fail 'The old key cannot be empty.'
IFS= read -r -s -p 'Paste the replacement OPENRAG_ENCRYPTION_KEY: ' new_key
printf '\n' >&2
[[ -n "$new_key" ]] || fail 'The replacement key cannot be empty.'
[[ "$old_key" != "$new_key" ]] || fail 'The old and replacement keys must differ.'

printf '[STEP] Writing both keys to protected files.\n' >&2
if [[ ! -d "$MIGRATION_DIR" ]]; then
  mkdir -m 700 -- "$MIGRATION_DIR"
fi
mkdir -m 700 -- "$keys" || fail 'Key directory already exists; nothing was overwritten.'
printf '%s\n' "$old_key" > "$keys/old"
printf '%s\n' "$new_key" > "$keys/new"
unset old_key new_key
printf '[OK] Both key files saved. No data files were changed.\n' >&2
