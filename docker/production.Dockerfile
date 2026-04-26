# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS node-builder

WORKDIR /app/theme/static_src

COPY theme/static_src/package.json theme/static_src/package-lock.json ./

RUN --mount=type=cache,target=/root/.npm npm ci

COPY theme/static_src/ ./
COPY hasta_la_vista_money/ /app/hasta_la_vista_money/
COPY config/ /app/config/
COPY core/ /app/core/
COPY static/ /app/static/

RUN npm run build


FROM python:3.13.9-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv==0.7.13

COPY pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv lock && uv sync --locked --no-dev --no-install-project

COPY manage.py ./
COPY config/ ./config/
COPY core/ ./core/
COPY hasta_la_vista_money/ ./hasta_la_vista_money/
COPY locale/ ./locale/
COPY theme/ ./theme/
COPY static/ ./static/
COPY docker/entrypoint.sh docker/celery-entrypoint.sh ./docker/

COPY --from=node-builder /app/static/css/styles.min.css ./static/css/styles.min.css


FROM python:3.13.9-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libgl1 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* && \
    pip install uv==0.7.13 && \
    adduser --disabled-password --gecos '' appuser

ENV PATH="/app/.venv/bin:/usr/local/bin:/home/appuser/.local/bin:$PATH"

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/manage.py /app/manage.py
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/pyproject.toml
COPY --from=builder --chown=appuser:appuser /app/config /app/config
COPY --from=builder --chown=appuser:appuser /app/core /app/core
COPY --from=builder --chown=appuser:appuser /app/hasta_la_vista_money /app/hasta_la_vista_money
COPY --from=builder --chown=appuser:appuser /app/locale /app/locale
COPY --from=builder --chown=appuser:appuser /app/theme /app/theme
COPY --from=builder --chown=appuser:appuser /app/static /app/static
COPY --from=builder /app/docker/entrypoint.sh /app/entrypoint.sh
COPY --from=builder /app/docker/celery-entrypoint.sh /app/celery-entrypoint.sh

RUN sed -i 's/\r$//' /app/entrypoint.sh /app/celery-entrypoint.sh && \
    chmod +x /app/entrypoint.sh /app/celery-entrypoint.sh && \
    mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/media /app/logs && \
    chmod -R 755 /app/staticfiles /app/media /app/logs

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD granian --interface asgi config.asgi:application --port 8001 --host 0.0.0.0 --workers ${GRANIAN_WORKERS:-2} --runtime-threads ${GRANIAN_RUNTIME_THREADS:-${GRANIAN_THREADS:-1}} --blocking-threads ${GRANIAN_BLOCKING_THREADS:-1}
