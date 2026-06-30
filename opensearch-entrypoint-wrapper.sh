#!/bin/bash
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

set -e

# Start OpenSearch in the background
/usr/share/opensearch/opensearch-docker-entrypoint.sh opensearch &
OPENSEARCH_PID=$!

# Function to handle shutdown signals
shutdown() {
    echo "Received shutdown signal, stopping OpenSearch gracefully..."
    kill -TERM "$OPENSEARCH_PID" 2>/dev/null || true
    # Wait up to 90s for graceful stop, then force-kill
    for i in $(seq 1 90); do
        kill -0 "$OPENSEARCH_PID" 2>/dev/null || break
        sleep 1
    done
    kill -KILL "$OPENSEARCH_PID" 2>/dev/null || true
    wait "$OPENSEARCH_PID"
    echo "OpenSearch stopped"
    exit 0
}

# Trap shutdown signals
trap shutdown SIGTERM SIGINT

# Run security setup in background after a delay
(
    sleep 15
    echo "Running security setup..."
    /usr/share/opensearch/setup-security.sh || echo "Security setup failed or already configured"
) &

# Wait for OpenSearch process
wait "$OPENSEARCH_PID"

