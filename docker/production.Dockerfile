FROM python:3.13.9-alpine AS builder

WORKDIR /app

RUN pip install uv==0.7.13

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

COPY . .

FROM python:3.13-slim

WORKDIR /app

RUN pip install uv==0.7.13

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]' && \
    adduser --disabled-password --gecos '' appuser

COPY --from=builder /app /app

RUN chown -R appuser:appuser /app && \
    chmod +x /app/.venv/bin/granian && \
    chmod +x /app/.venv/bin/python

USER appuser

COPY --chown=appuser:appuser docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
