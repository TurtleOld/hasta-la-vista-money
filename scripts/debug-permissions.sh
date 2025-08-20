#!/bin/bash

# Debug script for Docker permission issues
echo "=== Docker Permission Debug Script ==="

# Build the production image
echo "Building production Docker image..."
docker build -f docker/production.Dockerfile -t hasta-la-vista-money:debug .

# Run container with interactive shell to debug
echo "Running container with interactive shell..."
docker run --rm -it hasta-la-vista-money:debug /bin/bash -c "
echo '=== Container Debug Information ==='
echo 'Current user:'
whoami
echo ''
echo 'Current directory:'
pwd
echo ''
echo 'Directory permissions:'
ls -la /app/
echo ''
echo 'Staticfiles directory:'
ls -la /app/staticfiles/ 2>/dev/null || echo 'staticfiles directory not found'
echo ''
echo 'Bootstrap directory in static:'
ls -la /app/static/bootstrap/ 2>/dev/null || echo 'bootstrap directory not found'
echo ''
echo 'Testing collectstatic manually:'
cd /app && .venv/bin/python manage.py collectstatic --noinput --clear --verbosity=2
echo ''
echo 'Final staticfiles structure:'
find /app/staticfiles -type d | head -20
echo ''
echo '=== Debug Complete ==='
"
