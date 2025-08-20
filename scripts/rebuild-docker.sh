#!/bin/bash

echo "Stopping and removing all containers..."
docker-compose down

echo "Removing all volumes..."
docker volume prune -f

echo "Removing all images..."
docker rmi $(docker images -q) 2>/dev/null || true

echo "Building and starting containers..."
docker-compose up --build -d

echo "Showing logs..."
docker-compose logs -f
