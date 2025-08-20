FROM python:3.13-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl>=8.0 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

COPY . .

RUN mkdir -p /app/staticfiles && \
    .venv/bin/python manage.py collectstatic --noinput --clear

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl>=8.0 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup appuser

COPY --from=builder /app /app
COPY --from=builder /app/staticfiles /app/staticfiles

RUN chown -R appuser:appgroup /app && \
    chmod +x /app/.venv/bin/granian && \
    chmod +x /app/.venv/bin/python && \
    chmod -R 755 /app/staticfiles

USER appuser

COPY --chown=appuser:appgroup docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
