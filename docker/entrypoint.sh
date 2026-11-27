#!/bin/sh
# Container start-up: make sure the volume folders exist and hold the starter models, then run the server.
set -e
mkdir -p /app/data /app/models /app/runs /app/configs
for f in /app/starter-models/*.pt; do
  [ -e "$f" ] || continue
  [ -e "/app/models/$(basename "$f")" ] || cp "$f" /app/models/
done
# exec so the server is PID 1 and gets docker's stop signal: it saves profiles and boards on the way out
exec "$@"
