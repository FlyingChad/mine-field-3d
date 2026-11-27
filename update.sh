#!/bin/sh
# Pull the latest code from GitHub and rebuild and restart the container. Player data is kept
# (it lives in docker-data/). Games in progress end when the server restarts.
set -e
cd "$(dirname "$0")"
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
