FROM python:3.14-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv==0.7.13 \
    && adduser --disabled-password --gecos '' appuser

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:/home/appuser/.local/bin:$PATH"
ENV PYTHONPATH="/app/receipt_inference/src"

WORKDIR /app/receipt_inference

RUN mkdir -p /opt/venv /models && \
    chown -R appuser:appuser /app /opt/venv /models

COPY --chown=appuser:appuser receipt_inference/pyproject.toml ./pyproject.toml

USER appuser

RUN --mount=type=cache,target=/tmp/uv-cache,uid=1000,gid=1000 \
    UV_CACHE_DIR=/tmp/uv-cache uv lock && \
    UV_CACHE_DIR=/tmp/uv-cache uv sync --no-dev

COPY --chown=appuser:appuser receipt_inference/ ./

ENV PYTHONFAULTHANDLER=1 \
    PYTHONPATH=/app/receipt_inference/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["granian", "--interface", "asgi", "receipt_inference.app:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", "--runtime-threads", "1", "--blocking-threads", "1"]
