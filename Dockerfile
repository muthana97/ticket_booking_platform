# Lightweight image for Render (free tier) — single-worker uvicorn.
# When you upgrade to a paid plan, bump `--workers` and split off the Reaper
# into a separate process (see notes in claude.md).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg2 + bcrypt (already binary wheels, but keep for safety)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

# Source — copy backend src and the frontend bundle FastAPI serves at /app
COPY backend/src        /app/src
COPY backend/seed.py    /app/seed.py
COPY frontend           /app/frontend

# Render injects PORT at runtime; uvicorn binds to it.
ENV PORT=8000
EXPOSE 8000

# Single worker on the free tier — keeps the in-process Reaper from
# multiplying. Upgrade path is documented in claude.md.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
