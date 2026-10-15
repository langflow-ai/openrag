#!/bin/sh
set -eu

PLACEHOLDER="/NEXT_PUBLIC_BASE_PATH_PLACEHOLDER_a1b2c3d4"

# OPENRAG_FRONTEND_BASE_PATH is the documented OpenRAG setting.
TARGET_PATH="${OPENRAG_FRONTEND_BASE_PATH:-}"

if [ "$TARGET_PATH" = "/" ]; then
  TARGET_PATH=""
elif [ -n "$TARGET_PATH" ]; then
  case "$TARGET_PATH" in
    /*) ;;
    *) TARGET_PATH="/$TARGET_PATH" ;;
  esac
  TARGET_PATH="$(printf '%s' "$TARGET_PATH" | sed 's:/*$::')"

  case "$TARGET_PATH" in
    *'?'*|*'#'*|*://*)
      echo "OPENRAG_FRONTEND_BASE_PATH must be a path such as /openrag-fe" >&2
      exit 1
      ;;
  esac
fi

echo "Replacing frontend base-path placeholder with: '${TARGET_PATH}'"

# Escape replacement metacharacters while keeping '/' valid in the path.
ESCAPED_TARGET_PATH="$(printf '%s' "$TARGET_PATH" | sed 's/[\\&|]/\\\\&/g')"

# `basePath` is present in server output and browser chunks. `server.js` is
# included for completeness when the standalone output changes between Next
# versions. The image filesystem is writable by the runtime UID.
find .next public server.js -type f 2>/dev/null \
  -exec sed -i "s|${PLACEHOLDER}|${ESCAPED_TARGET_PATH}|g" {} +

exec "$@"
