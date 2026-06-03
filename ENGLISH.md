# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/TurtleOld/hasta-la-vista-money)
[![Lines of Code](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0-green.svg)](https://www.djangoproject.com/)

**[🇷🇺 Русская версия](README.md)** | **[📚 Documentation](https://deepwiki.com/TurtleOld/hasta-la-vista-money)**

---

## Table of Contents

- [About the Project](#about-the-project)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Security](#security)
- [Contributing](#contributing)
- [Community & Support](#community--support)
- [License](#license)

---

## About the Project

**Hasta La Vista, Money!** is a modern open-source personal finance management system designed for self-hosting. Take full control of your financial data with powerful analytics, loan tracking, and budget planning tools.

### Why Hasta La Vista, Money?

- **Self-hosted** — full control over your data and infrastructure
- **Open Source** — transparent code, free Apache 2.0 license
- **Privacy** — your financial data stays on your server only
- **Easy deployment** — up and running with Docker Compose in minutes
- **Audit log** — immutable operation history with human-readable field labels

---

## Features

### Financial Accounting

- Manage multiple accounts with multi-currency support
- Track income and expenses through a unified transaction model
- Hierarchical categories
- Complete transaction history

### Receipt Processing

- QR code import from fiscal receipts
- Data retrieval via Russian FNS (tax authority) API
- Manual purchase entry
- Return receipts with automatic balance adjustment

### Analytics & Reports

- Statistics by period
- Interactive charts (Chart.js)
- Expense breakdown by category
- JSON data export

### Budgeting

- Income and expense planning
- Plan vs actual comparison
- Limit exceeded notifications

### Loans & Credit

- Loan and credit tracking
- Repayment schedule calculation with grace period support

### Security & Audit

- Immutable audit log with object names and human-readable field labels
- Rate limiting and brute-force protection (django-axes)
- JWT + session-based authentication
- CSRF, XSS, CSP, HSTS, Secure cookies

---

## Technology Stack

| Component | Technologies |
| --- | --- |
| **Backend** | Django 6.0.5, Python 3.12.7+, Django REST Framework 3.15, Celery 5.4 |
| **ASGI server** | Granian 2.3+ (HTTP/2, TLS) |
| **Frontend** | Tailwind CSS v4, DaisyUI 5, Chart.js, HTMX, driver.js, flatpickr |
| **Database** | PostgreSQL 18 (Docker), SQLite (local fallback) |
| **Cache & queues** | Redis 8, django-redis, django-celery-beat |
| **API** | RESTful, OpenAPI schema (drf-spectacular), Swagger UI |
| **Containerization** | Docker, Docker Compose, Nginx |
| **Security** | CSP, CSRF, JWT, django-axes, CORS, HSTS |
| **Code quality** | mypy (strict), ruff, pre-commit, coverage ≥ 85% |
| **Monitoring** | django-structlog (structured logs) |
| **Localization** | i18n, full Russian/English support |

---

## Quick Start

### Requirements

- Docker and Docker Compose
- A few GB of free disk space (Docker images, PostgreSQL, Redis)
- At least 1 GB of RAM

### Launch in 3 Steps

```bash
# 1. Clone the repository
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money

# 2. Create .env file
cat > .env << EOF
SECRET_KEY=$(openssl rand -base64 50)
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1
BASE_URL=http://127.0.0.1:8090
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8090,http://localhost:8090
EOF

# 3. Start the application
docker compose up -d
```

Open your browser and go to [http://127.0.0.1:8090](http://127.0.0.1:8090).

> `docker-compose.yaml` starts PostgreSQL, Redis, Celery worker/beat, the web application, and Nginx. SQLite is used only as a fallback for direct local runs without `DATABASE_URL`.

### Production Deployment

```bash
docker compose -f docker-compose.prod.yaml up -d
```

The production image is pulled from `ghcr.io/turtleold/hasta-la-vista-money:main`.

### First Steps

1. Register an account
2. Create your first financial account
3. Add income and expense categories
4. Start tracking your finances!

---

## Configuration

The application is configured through environment variables in the `.env` file.

### Main Variables

| Variable | Description | Default |
| --- | --- | --- |
| `SECRET_KEY` | Django secret key (required) | — |
| `DJANGO_SETTINGS_MODULE` | Settings module; for production: `config.django.prod` | `config.django.base` |
| `DEBUG` | Debug mode | `false` |
| `ALLOWED_HOSTS` | Allowed hosts | — |
| `BASE_URL` | Application base URL | `http://127.0.0.1:8000/` |
| `CSRF_TRUSTED_ORIGINS` | Trusted CSRF origins | — |
| `DATABASE_URL` | External PostgreSQL URL | — |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Built-in PostgreSQL credentials | `hlvm`, `postgres`, `postgres` |
| `REDIS_LOCATION` | Redis URL | — |
| `SESSION_COOKIE_SECURE` | `Secure` flag for session cookie | `true` |
| `CSRF_COOKIE_SECURE` | `Secure` flag for CSRF cookie | `true` |
| `SECURE_SSL_REDIRECT` | Force HTTPS redirect | `true` |
| `SECURE_HSTS_SECONDS` | HSTS `max-age` value | `31536000` |
| `ACCESS_TOKEN_LIFETIME` | JWT access token lifetime (minutes) | `60` |
| `REFRESH_TOKEN_LIFETIME` | JWT refresh token lifetime (days) | `7` |
| `LANGUAGE_CODE` | Interface language | `ru-RU` |
| `TIME_ZONE` | Timezone | `Europe/Moscow` |
| `FNS_BASE_URL` | FNS API base URL | `https://irkkt-mobile.nalog.ru:8888/v2` |
| `FNS_INN` | FNS account INN | — |
| `FNS_PASSWORD` | FNS account password | — |
| `FNS_CLIENT_SECRET` | FNS API client secret | — |
| `FNS_TIMEOUT_SECONDS` | FNS request timeout (sec) | `10` |

### Production Minimum

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
FNS_INN, FNS_PASSWORD, FNS_CLIENT_SECRET  # for receipt processing
```

### Redis

Redis is used for caching, sessions, rate limiting, and as a Celery task broker.

What is cached:

- Category tree (TTL: 5 minutes)
- User statistics (TTL: 10 minutes)
- Account list (TTL: 5 minutes)
- User sessions

```bash
# Verify Redis is running
docker exec -it hlvm-prod-redis-1 redis-cli ping
# Expected: PONG
```

---

## Security

- CSRF and XSS attack protection
- Content Security Policy (CSP)
- JWT authentication for API
- SQL injection protection via Django ORM
- Rate limiting (django-axes)
- Secure password storage via Django password hashers
- Docker containers run as non-privileged user `appuser`
- HSTS, Secure cookies, HTTPS redirect

---

## Contributing

### Process

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/hasta-la-vista-money.git

# 2. Create a branch
git checkout -b feature/amazing-feature

# 3. Install dependencies
make install

# 4. Run tests
make test

# 5. Create a Pull Request
```

### Useful Commands (Makefile)

```bash
make install             # install dependencies (uv)
make test                # run tests
make coverage            # coverage report (threshold: 85%)
make lint                # ruff + mypy checks
make format              # format code
make migrate             # apply migrations
make staticfiles         # collect static files
make build-js            # build CSS/JS (Tailwind v4)
make export-api-schema   # export OpenAPI schema
```

### Note on uv.lock

`uv.lock` is not stored in the repository — it is generated automatically during Docker image builds and when running `make install`. To update dependencies: `uv lock --upgrade`.

---

## API Documentation

Available in a running application:

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/schema/swagger-ui/`

---

## Community & Support

- [GitHub Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions) — discussions, questions, ideas
- [Issue Tracker](https://github.com/TurtleOld/hasta-la-vista-money/issues) — bugs and feature requests
- [DeepWiki](https://deepwiki.com/TurtleOld/hasta-la-vista-money) — project documentation
- [Email](mailto:dev@pavlovteam.ru) — direct contact with the developer

---

## License

This project is licensed under the **Apache License 2.0**.
See the [LICENSE](LICENSE) file for details.

```text
Copyright 2022-2025 Alexander Pavlov (TurtleOld)
Licensed under the Apache License, Version 2.0
```

---

**Hasta La Vista, Money!** — your reliable assistant in personal finance management!

[📚 Documentation](https://deepwiki.com/TurtleOld/hasta-la-vista-money) • [🐛 Bug Reports](https://github.com/TurtleOld/hasta-la-vista-money/issues) • [💬 Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions)
