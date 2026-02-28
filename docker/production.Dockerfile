FROM node:20-alpine AS node-builder

WORKDIR /app

COPY theme/static_src/package.json theme/static_src/package-lock.json theme/static_src/

WORKDIR /app/theme/static_src

RUN npm ci

COPY theme/static_src/ ./

COPY hasta_la_vista_money/ ../../hasta_la_vista_money/
COPY config/ ../../config/
COPY core/ ../../core/
COPY static/ ../../static/

RUN npm run build

WORKDIR /app

FROM python:3.13.9-slim AS builder

WORKDIR /app

RUN pip install uv==0.7.13

ENV PATH="/root/.local/bin:$PATH"

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

COPY pyproject.toml ./

RUN if [ -f uv.lock ]; then \
      echo "Using existing uv.lock"; \
    else \
      echo "Generating uv.lock..."; \
      uv lock; \
    fi

RUN uv sync --dev

COPY . .

COPY --from=node-builder /app/static/css/styles.min.css static/css/styles.min.css

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

ENV PATH="/usr/local/bin:/home/appuser/.local/bin:$PATH"

COPY --from=builder /app /app

COPY --from=builder /app/docker/entrypoint.sh /app/entrypoint.sh
COPY --from=builder /app/docker/celery-entrypoint.sh /app/celery-entrypoint.sh

RUN chown -R appuser:appuser /app && \
    chmod +x /app/.venv/bin/granian && \
    chmod +x /app/.venv/bin/python && \
    sed -i 's/\r$//' /app/entrypoint.sh /app/celery-entrypoint.sh && \
    chmod +x /app/entrypoint.sh /app/celery-entrypoint.sh && \
    test -f /app/entrypoint.sh && \
    head -1 /app/entrypoint.sh && \
    mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/media /app/logs && \
    chmod -R 755 /app/staticfiles /app/media /app/logs

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
