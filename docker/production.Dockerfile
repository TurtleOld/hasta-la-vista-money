FROM python:3.13.5-slim as builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    curl -sSL https://install.python-poetry.org  | python3 -

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && \
    poetry export --with extras=psycopg2-binary --without-hashes --format=requirements.txt > requirements.prod.txt

FROM python:3.13.5-slim

WORKDIR /app

RUN adduser --disabled-password --gecos '' appuser
USER appuser
ENV HOME=/home/appuser
ENV PATH="$HOME/.local/bin:$PATH"

COPY --from=builder /app/requirements.prod.txt ./
RUN pip install --no-cache-dir --user -r requirements.prod.txt

COPY --chown=appuser:appuser . .

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["python", "manage.py", "migrate", "&&", "python", "manage.py", "collectstatic", "--noinput", "&&", "granian", "--interface", "asgi", "config.asgi:application", "--port", "8000", "--host", "0.0.0.0"]