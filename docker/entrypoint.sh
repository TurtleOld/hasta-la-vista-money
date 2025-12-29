#!/bin/bash
set -e

echo "Waiting for database connection..."
while ! python manage.py check --database default 2>&1; do
    echo "Database is unavailable - sleeping"
    sleep 2
done

echo "Database is up - executing migrations"
python manage.py migrate --noinput



echo "Creating staticfiles and logs directories with proper permissions"
mkdir -p /app/staticfiles /app/logs
chmod -R 755 /app/staticfiles /app/logs

echo "Collecting static files"
python manage.py collectstatic --noinput --clear

echo "Starting application"
exec "$@"
