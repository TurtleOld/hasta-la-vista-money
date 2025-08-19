FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl>=8.0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

RUN adduser --disabled-password --gecos '' appuser

COPY . .

# Create necessary directories and set proper ownership for entire app directory
RUN mkdir -p /app/staticfiles /app/logs && \
    chown -R appuser:appuser /app

USER appuser
RUN .venv/bin/python manage.py collectstatic --noinput --clear

CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
