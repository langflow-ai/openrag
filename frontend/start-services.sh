#!/bin/sh
set -e

echo "Starting metrics server on port 9090..."
node metrics-server.js &

echo "Starting Next.js frontend on port 3000..."
exec npm start
