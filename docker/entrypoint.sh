#!/bin/sh
set -e

echo "Waiting for database connection..."
while ! /app/.venv/bin/python manage.py check --database default 2>&1; do
    echo "Database is unavailable - sleeping"
    sleep 2
done

echo "Database is up - executing migrations"
/app/.venv/bin/python manage.py migrate --noinput

echo "Creating staticfiles, media and logs directories with proper permissions"
mkdir -p /app/staticfiles /app/media /app/logs
chmod -R 755 /app/staticfiles /app/media /app/logs

echo "Collecting static files"
/app/.venv/bin/python manage.py collectstatic --noinput --clear

echo "Starting application"
exec "$@"
