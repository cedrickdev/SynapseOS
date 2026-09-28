# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY apps ./apps
COPY alembic ./alembic
COPY core ./core
COPY infrastructure ./infrastructure

RUN pip install --upgrade pip \
    && pip install . \
    && useradd --create-home --uid 1000 synapse \
    && mkdir -p /var/lib/synapseos/workspaces \
    && chown --recursive synapse:synapse /var/lib/synapseos

USER synapse
STOPSIGNAL SIGTERM

FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM runtime AS worker
CMD ["python", "-m", "apps.worker.main"]

FROM runtime AS migrate
CMD ["alembic", "upgrade", "head"]

FROM runtime AS smoke
CMD ["python", "-m", "apps.smoke.main"]
