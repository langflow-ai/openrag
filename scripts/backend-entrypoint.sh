#!/bin/sh
# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

# backend-entrypoint.sh — run as root, fix volume-mount ownership, then drop to appuser.
#
# When Docker (not Podman) mounts a host directory the ownership reflects the
# host filesystem, which may not be UID/GID 1000. Podman handles this with the
# :U compose flag; this script is the belt-and-suspenders fallback for Docker
# and any other runtime that does not remap UIDs automatically.
#
# Each path listed below corresponds to a volume mount in docker-compose.yml.
# The chown is a no-op when the directory is already owned by appuser (e.g.
# fresh Podman start), so there is no cost to running this unconditionally.

set -e

if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser \
        /app/keys \
        /app/flows \
        /app/config \
        /app/data \
        /app/openrag-documents \
        2>/dev/null || true
    exec runuser -u appuser -- env \
        VIRTUAL_ENV=/app/.venv \
        PATH="/app/.venv/bin:$PATH" \
        "$@"
else
    exec "$@"
fi
