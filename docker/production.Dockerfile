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

FROM python:3.13.9-alpine AS builder

WORKDIR /app

RUN pip install uv==0.7.13

ENV PATH="/root/.local/bin:$PATH"

RUN apk add --no-cache gcc python3-dev musl-dev linux-headers

COPY pyproject.toml uv.lock ./

RUN uv sync --dev

COPY . .

COPY --from=node-builder /app/static/css/styles.min.css static/css/styles.min.css

FROM python:3.13.9-alpine

WORKDIR /app

RUN pip install uv==0.7.13 && \
    adduser --disabled-password --gecos '' appuser

ENV PATH="/usr/local/bin:/home/appuser/.local/bin:$PATH"

COPY --from=builder /app /app

COPY docker/entrypoint.sh /tmp/entrypoint.sh

RUN chown -R appuser:appuser /app && \
    chmod +x /app/.venv/bin/granian && \
    chmod +x /app/.venv/bin/python && \
    sed -i 's/\r$//' /tmp/entrypoint.sh && \
    mv /tmp/entrypoint.sh /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh && \
    ls -la /app/entrypoint.sh && \
    mkdir -p /app/staticfiles /app/logs && \
    chown -R appuser:appuser /app/staticfiles /app/logs && \
    chmod -R 755 /app/staticfiles /app/logs

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]