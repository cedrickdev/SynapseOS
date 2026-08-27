# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Phase 6 Git tools invoke this fixed executable directly without a shell.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy metadata + sources needed to build/install the package.
COPY pyproject.toml README.md alembic.ini ./
COPY apps ./apps
COPY alembic ./alembic
COPY core ./core
COPY infrastructure ./infrastructure

RUN pip install --upgrade pip && pip install .

# Run as an unprivileged user (least privilege — Company Constitution).
RUN useradd --create-home --uid 1000 synapse
USER synapse

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
