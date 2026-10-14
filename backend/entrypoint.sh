#!/bin/sh
set -e
python -m app.preflight
if [ "$RUN_MIGRATIONS" = "true" ]; then
  alembic upgrade head
  python -m app.seed
fi
exec "$@"
