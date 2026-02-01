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
    gcc=4:13.2.0-1 \
    g++=4:13.2.0-1 \
    libglib2.0-0=2.80.0-1 \
    libsm6=2:1.2.4-1 \
    libxext6=2:1.3.6-1 \
    libxrender-dev=1:0.9.11-1 \
    libgomp1=14.1.0-1 \
    libgl1=1.7.0-1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN uv sync --dev

COPY . .

COPY --from=node-builder /app/static/css/styles.min.css static/css/styles.min.css

FROM python:3.13.9-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0=2.80.0-1 \
    libsm6=2:1.2.4-1 \
    libxext6=2:1.3.6-1 \
    libxrender1=2:0.9.11-1 \
    libgomp1=14.1.0-1 \
    libgl1=1.7.0-1 \
    && rm -rf /var/lib/apt/lists/* && \
    pip install uv==0.7.13 && \
    adduser --disabled-password --gecos '' appuser

ENV PATH="/usr/local/bin:/home/appuser/.local/bin:$PATH"

COPY --from=builder /app /app

COPY --from=builder /app/docker/entrypoint.sh /app/entrypoint.sh

RUN chown -R appuser:appuser /app && \
    chmod +x /app/.venv/bin/granian && \
    chmod +x /app/.venv/bin/python && \
    sed -i 's/\r$//' /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh && \
    test -f /app/entrypoint.sh && \
    head -1 /app/entrypoint.sh && \
    mkdir -p /app/staticfiles /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/logs && \
    chmod -R 755 /app/staticfiles /app/logs

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
