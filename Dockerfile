# pull official base image
FROM debian:bookworm-slim

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.4.0

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir "poetry==$POETRY_VERSION"
RUN apk --no-cache add make
