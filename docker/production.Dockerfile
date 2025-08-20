FROM python:3.13-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl>=8.0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

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
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

RUN adduser --disabled-password --gecos '' appuser

COPY --from=builder /app /app
COPY --from=builder /app/staticfiles /app/staticfiles

RUN chown -R appuser:appuser /app

USER appuser

CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]

