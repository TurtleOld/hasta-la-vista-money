FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./

RUN uv venv .venv && uv pip install -e '.[dev]'

COPY . .

# Create staticfiles directory
RUN mkdir -p /app/staticfiles

RUN .venv/bin/python manage.py collectstatic --noinput --clear

RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

CMD [".venv/bin/granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]
