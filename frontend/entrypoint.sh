#!/bin/sh
set -eu

PLACEHOLDER="/NEXT_PUBLIC_BASE_PATH_PLACEHOLDER_a1b2c3d4"
RUNTIME_DIR="${OPENRAG_FRONTEND_RUNTIME_DIR:-/tmp/openrag-frontend}"

# OPENRAG_FRONTEND_BASE_PATH is the documented OpenRAG setting.
TARGET_PATH="${OPENRAG_FRONTEND_BASE_PATH:-}"
TARGET_PATH="$(printf '%s' "$TARGET_PATH" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [ "$TARGET_PATH" = "/" ]; then
  TARGET_PATH=""
elif [ -n "$TARGET_PATH" ]; then
  case "$TARGET_PATH" in
    /*) ;;
    *) TARGET_PATH="/$TARGET_PATH" ;;
  esac
  TARGET_PATH="$(printf '%s' "$TARGET_PATH" | sed 's:/*$::')"

  # The value is inserted into generated JavaScript and JSON. Restrict it to
  # URL-path characters that are safe in each generated asset format.
  case "$TARGET_PATH" in
    *[!A-Za-z0-9/._~-]*)
      echo "OPENRAG_FRONTEND_BASE_PATH may only contain letters, digits, '/', '.', '_', '~' and '-'" >&2
      exit 1
      ;;
  esac
fi

echo "Replacing frontend base-path placeholder with: '${TARGET_PATH}'"

# Next.js embeds basePath into server output and browser chunks. Do not mutate
# the image layer: Kubernetes commonly makes it read-only. Copy the standalone
# app to a pod-writable directory, patch that copy, and run it from there.
# Do not preserve ownership: OpenShift can run the container as an arbitrary
# non-root UID, which cannot restore the image files' original owner.
if ! mkdir -p "$RUNTIME_DIR" || ! cp -R . "$RUNTIME_DIR"; then
  echo "Unable to prepare frontend runtime assets in $RUNTIME_DIR." >&2
  echo "Mount a writable volume at /tmp or set OPENRAG_FRONTEND_RUNTIME_DIR." >&2
  exit 1
fi

if ! find "$RUNTIME_DIR/.next" "$RUNTIME_DIR/public" "$RUNTIME_DIR/server.js" \
  -type f 2>/dev/null \
  -exec sed -i "s|${PLACEHOLDER}|${TARGET_PATH}|g" {} +; then
  echo "Unable to apply OPENRAG_FRONTEND_BASE_PATH to runtime assets." >&2
  exit 1
fi

cd "$RUNTIME_DIR"
exec "$@"
