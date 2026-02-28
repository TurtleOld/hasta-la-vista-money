#!/bin/sh
set -e

DB_HOST=$(echo "${DATABASE_URL:-postgres://postgres:postgres@db:5432/hlvm}" | sed 's|.*@\([^:/]*\).*|\1|')
DB_PORT=$(echo "${DATABASE_URL:-postgres://postgres:postgres@db:5432/hlvm}" | sed 's|.*:\([0-9]*\)/.*|\1|')

echo "Waiting for database connection at ${DB_HOST}:${DB_PORT}..."
until nc -z "${DB_HOST}" "${DB_PORT}" 2>/dev/null; do
    echo "Database is unavailable - sleeping"
    sleep 2
done

echo "Database is up - executing migrations"
uv run python manage.py migrate --noinput

echo "Creating staticfiles, media and logs directories with proper permissions"
mkdir -p /app/staticfiles /app/media /app/logs
chmod -R 755 /app/staticfiles /app/media /app/logs

echo "Collecting static files"
uv run python manage.py collectstatic --noinput --clear

echo "Starting application"
exec "$@"
