# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# Prevents Python from writing .pyc files and buffering stdout/stderr --
# buffered logs would otherwise delay showing up in `docker logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: gcc/libpq-dev needed to build psycopg if a wheel isn't
# available for the target platform; psycopg[binary] usually ships
# prebuilt wheels, but keeping these avoids a fragile image on
# uncommon architectures (e.g. some ARM hosts).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Data dir kept for any local/dev fallback usage; not required for
# Postgres-backed persistence, but harmless to ensure it exists.
RUN mkdir -p /app/data

# EXPOSE 8000

# No --reload in the image -- reload is a dev-only convenience, wired
# in via docker-compose.override or a separate dev command instead.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]