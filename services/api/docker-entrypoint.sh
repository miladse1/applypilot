#!/bin/sh
set -eu

python - <<'PY'
import os
import time

from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if url.startswith("sqlite"):
    raise SystemExit(0)
engine = create_engine(url)
for attempt in range(30):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Database did not become available.")
PY

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
