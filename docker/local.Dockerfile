
FROM python:3.13.9-alpine

# Install system dependencies for camelot-py PDF processing
RUN apk add --no-cache \
    ghostscript \
    tk \
    build-base \
    libffi-dev \
    && pip install uv==0.7.13 \
    && adduser --disabled-password --gecos '' appuser

ENV PATH="/usr/local/bin:/home/appuser/.local/bin:$PATH"

WORKDIR /app

COPY --chown=appuser:appuser pyproject.toml uv.lock ./

USER appuser

RUN uv sync --dev

COPY --chown=appuser:appuser . .

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
