# API Documentation

Документация API для проекта Hasta La Vista, Money!. API предоставляет endpoints для управления финансами, чеками, бюджетами и аутентификации.

## Обзор

API построен на базе Django REST Framework и использует OpenAPI 3.0 спецификацию для описания endpoints.

## Аутентификация

API использует JWT токены для аутентификации. Для получения токена используйте endpoint `/api/auth/token/`.

## Документация API

Ниже представлена интерактивная документация API, созданная с помощью Swagger UI:

!!swagger schema.json!!
