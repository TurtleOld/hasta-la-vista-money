#!/bin/bash
set -e

# Ждем подключения к базе данных
echo "Waiting for database connection..."
while ! .venv/bin/python manage.py check --database default 2>&1; do
    echo "Database is unavailable - sleeping"
    sleep 2
done

echo "Database is up - executing migrations"
.venv/bin/python manage.py migrate --noinput

echo "Creating staticfiles and logs directories with proper permissions"
mkdir -p /app/staticfiles /app/logs
chmod -R 755 /app/staticfiles /app/logs

echo "Collecting static files"
.venv/bin/python manage.py collectstatic --noinput --clear

echo "Starting application"
exec "$@"
