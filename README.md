# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/TurtleOld/hasta-la-vista-money)
[![Lines of Code](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0-green.svg)](https://www.djangoproject.com/)

**[🇺🇸 English version](ENGLISH.md)** | **[📚 Документация](https://deepwiki.com/TurtleOld/hasta-la-vista-money)**

---

## Содержание

- [О проекте](#о-проекте)
- [Возможности](#возможности)
- [Технологический стек](#технологический-стек)
- [Быстрый старт](#быстрый-старт)
- [Конфигурация](#конфигурация)
- [Безопасность](#безопасность)
- [Участие в разработке](#участие-в-разработке)
- [Сообщество и поддержка](#сообщество-и-поддержка)
- [Лицензия](#лицензия)

---

## О проекте

**Hasta La Vista, Money!** — современная система управления личными финансами с открытым исходным кодом для самостоятельного развёртывания. Получите полный контроль над своими финансовыми данными с мощными инструментами аналитики, учёта кредитов и планирования бюджета.

### Почему Hasta La Vista, Money?

- **Self-hosted** — полный контроль над данными и инфраструктурой
- **Open Source** — прозрачный код, свободная лицензия Apache 2.0
- **Приватность** — ваши финансовые данные остаются только на вашем сервере
- **Простое развёртывание** — запуск через Docker Compose в несколько команд
- **Русский язык** — полностью локализованный интерфейс
- **Audit log** — неизменяемый журнал всех операций с читаемыми метками полей

---

## Возможности

### Финансовый учёт

- Управление множеством счетов с поддержкой различных валют
- Учёт доходов и расходов через единую модель транзакций
- Иерархические категории
- Полная история всех операций

### Обработка чеков

- Импорт по QR-коду чека
- Получение данных через API ФНС
- Ручное добавление покупок
- Возврат чека с корректировкой баланса

### Аналитика и отчёты

- Статистика по периодам
- Интерактивные графики (Chart.js)
- Анализ расходов по категориям
- Экспорт данных в JSON

### Бюджетирование

- Планирование доходов и расходов
- Сравнение план/факт
- Уведомления о превышении лимитов

### Кредиты и займы

- Учёт кредитов и займов
- Расчёт графика погашений с поддержкой льготного периода

### Безопасность и аудит

- Неизменяемый audit log с именами объектов и читаемыми метками полей
- Rate limiting и защита от брутфорса (django-axes)
- JWT + сессионная аутентификация
- CSRF, XSS, CSP, HSTS, Secure cookies

---

## Технологический стек

| Компонент | Технологии |
| --- | --- |
| **Backend** | Django 6.0.5, Python 3.12.7+, Django REST Framework 3.15, Celery 5.4 |
| **ASGI-сервер** | Granian 2.3+ (HTTP/2, TLS) |
| **Frontend** | Tailwind CSS v4, DaisyUI 5, Chart.js, HTMX, driver.js, flatpickr |
| **База данных** | PostgreSQL 18 (Docker), SQLite (локальный fallback) |
| **Кеш и очереди** | Redis 8, django-redis, django-celery-beat |
| **API** | RESTful, OpenAPI schema (drf-spectacular), Swagger UI |
| **Контейнеризация** | Docker, Docker Compose, Nginx |
| **Безопасность** | CSP, CSRF, JWT, django-axes, CORS, HSTS |
| **Качество кода** | mypy (strict), ruff, pre-commit, coverage ≥ 85% |
| **Мониторинг** | django-structlog (структурированные логи) |
| **Локализация** | i18n, полная поддержка русского языка |

---

## Быстрый старт

### Требования

- Docker и Docker Compose
- Несколько ГБ свободного места (Docker-образы, PostgreSQL, Redis)
- От 1 ГБ оперативной памяти

### Запуск за 3 шага

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money

# 2. Создайте файл .env
cat > .env << EOF
SECRET_KEY=$(openssl rand -base64 50)
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1
BASE_URL=http://127.0.0.1:8090
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8090,http://localhost:8090
EOF

# 3. Запустите приложение
docker compose up -d
```

Откройте браузер и перейдите по адресу [http://127.0.0.1:8090](http://127.0.0.1:8090).

> `docker-compose.yaml` поднимает PostgreSQL, Redis, Celery worker/beat, веб-приложение и Nginx. SQLite используется только как fallback при прямом локальном запуске без `DATABASE_URL`.

### Production-развёртывание

```bash
docker compose -f docker-compose.prod.yaml up -d
```

Production-образ берётся из `ghcr.io/turtleold/hasta-la-vista-money:main`.

### Первые шаги

1. Зарегистрируйте аккаунт
2. Создайте финансовый счёт
3. Добавьте категории доходов и расходов
4. Начните вести учёт!

---

## Конфигурация

Приложение настраивается через переменные окружения в файле `.env`.

### Основные переменные

| Переменная | Описание | По умолчанию |
| --- | --- | --- |
| `SECRET_KEY` | Секретный ключ Django (обязательно) | — |
| `DJANGO_SETTINGS_MODULE` | Модуль настроек; для production: `config.django.prod` | `config.django.base` |
| `DEBUG` | Режим отладки | `false` |
| `ALLOWED_HOSTS` | Разрешённые хосты | — |
| `BASE_URL` | Базовый URL приложения | `http://127.0.0.1:8000/` |
| `CSRF_TRUSTED_ORIGINS` | Доверенные источники для CSRF | — |
| `DATABASE_URL` | URL внешней PostgreSQL | — |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Параметры встроенной PostgreSQL | `hlvm`, `postgres`, `postgres` |
| `REDIS_LOCATION` | URL Redis | — |
| `SESSION_COOKIE_SECURE` | Флаг `Secure` для session cookie | `true` |
| `CSRF_COOKIE_SECURE` | Флаг `Secure` для CSRF cookie | `true` |
| `SECURE_SSL_REDIRECT` | Принудительный редирект на HTTPS | `true` |
| `SECURE_HSTS_SECONDS` | Значение `max-age` для HSTS | `31536000` |
| `ACCESS_TOKEN_LIFETIME` | Время жизни JWT access token (минуты) | `60` |
| `REFRESH_TOKEN_LIFETIME` | Время жизни JWT refresh token (дни) | `7` |
| `LANGUAGE_CODE` | Язык интерфейса | `ru-RU` |
| `TIME_ZONE` | Часовой пояс | `Europe/Moscow` |
| `FNS_BASE_URL` | Базовый URL API ФНС | `https://irkkt-mobile.nalog.ru:8888/v2` |
| `FNS_INN` | ИНН аккаунта ФНС | — |
| `FNS_PASSWORD` | Пароль аккаунта ФНС | — |
| `FNS_CLIENT_SECRET` | Client secret API ФНС | — |
| `FNS_TIMEOUT_SECONDS` | Таймаут запросов к ФНС (сек) | `10` |

### Минимум для production

```text
SECRET_KEY
DJANGO_SETTINGS_MODULE=config.django.prod
DEBUG=false
ALLOWED_HOSTS
BASE_URL
CSRF_TRUSTED_ORIGINS
REDIS_LOCATION
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS, SECURE_HSTS_INCLUDE_SUBDOMAINS, SECURE_HSTS_PRELOAD
FNS_INN, FNS_PASSWORD, FNS_CLIENT_SECRET  # для обработки чеков
```

### Redis

Redis используется для кеширования, сессий, rate limiting и брокера задач Celery.

Что кешируется:

- Дерево категорий (TTL: 5 минут)
- Статистика пользователя (TTL: 10 минут)
- Список счетов (TTL: 5 минут)
- Сессии пользователей

```bash
# Проверка работы Redis
docker exec -it hlvm-prod-redis-1 redis-cli ping
# Ответ: PONG
```

---

## Безопасность

- Защита от CSRF и XSS атак
- Content Security Policy (CSP)
- JWT-аутентификация для API
- Защита от SQL-инъекций через Django ORM
- Rate limiting (django-axes)
- Безопасное хранение паролей через password hashers Django
- Docker-контейнеры работают от непривилегированного пользователя `appuser`
- HSTS, Secure cookies, HTTPS redirect

---

## Участие в разработке

### Процесс

```bash
# 1. Форкните и клонируйте репозиторий
git clone https://github.com/YOUR_USERNAME/hasta-la-vista-money.git

# 2. Создайте ветку
git checkout -b feature/amazing-feature

# 3. Установите зависимости
make install

# 4. Протестируйте изменения
make test

# 5. Создайте Pull Request
```

### Полезные команды (Makefile)

```bash
make install             # установка зависимостей (uv)
make test                # запуск тестов
make coverage            # отчёт о покрытии (порог: 85%)
make lint                # проверка ruff + mypy
make format              # форматирование кода
make migrate             # применение миграций
make staticfiles         # сборка статики
make build-js            # сборка CSS/JS (Tailwind v4)
make export-api-schema   # экспорт OpenAPI схемы
```

### Важно: uv.lock

`uv.lock` не хранится в репозитории — генерируется автоматически при сборке Docker-образов и при `make install`. Для обновления зависимостей: `uv lock --upgrade`.

---

## API документация

В запущенном приложении доступны:

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/schema/swagger-ui/`

---

## Сообщество и поддержка

- [GitHub Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions) — обсуждения, вопросы, идеи
- [Issue Tracker](https://github.com/TurtleOld/hasta-la-vista-money/issues) — баги и запросы на функции
- [DeepWiki](https://deepwiki.com/TurtleOld/hasta-la-vista-money) — документация проекта

---

## Лицензия

Проект распространяется под лицензией **Apache License 2.0**.
См. файл [LICENSE](LICENSE) для подробностей.

```text
Copyright 2022-2025 Alexander Pavlov (TurtleOld)
Licensed under the Apache License, Version 2.0
```

---

**Hasta La Vista, Money!** — ваш надёжный помощник в управлении личными финансами!

[📚 Документация](https://deepwiki.com/TurtleOld/hasta-la-vista-money) • [🐛 Баг-репорты](https://github.com/TurtleOld/hasta-la-vista-money/issues) • [💬 Обсуждения](https://github.com/TurtleOld/hasta-la-vista-money/discussions)
