#!/bin/sh
set -e

echo "Waiting for database connection..."
until /app/.venv/bin/python manage.py check --database default > /dev/null 2>&1; do
    echo "Database is unavailable - sleeping"
    sleep 2
done

echo "Database is up - starting Celery worker"
exec "$@"
