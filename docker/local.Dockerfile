# syntax=docker/dockerfile:1.7

FROM python:3.13.9-slim

# Install system dependencies for camelot-py PDF processing.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    ghostscript \
    libffi-dev \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv==0.7.13 \
    && adduser --disabled-password --gecos '' appuser

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:/home/appuser/.local/bin:$PATH"

WORKDIR /app

RUN mkdir -p /opt/venv && \
    chown -R appuser:appuser /app /opt/venv

COPY --chown=appuser:appuser pyproject.toml ./

USER appuser

RUN --mount=type=cache,target=/tmp/uv-cache,uid=1000,gid=1000 \
    UV_CACHE_DIR=/tmp/uv-cache uv lock && \
    UV_CACHE_DIR=/tmp/uv-cache uv sync --dev

COPY --chown=appuser:appuser . .

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8001"]
