# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yml)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/TurtleOld/hasta-la-vista-money)
[![Lines of Code](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0-green.svg)](https://www.djangoproject.com/)

**[🇺🇸 English version](ENGLISH.md)** | **[📚 Документация](https://hasta-la-vista-money.readthedocs.io/)**

---

## 🎯 О проекте

**Hasta La Vista, Money!** — это современная система управления личными финансами с открытым исходным кодом для самостоятельного развертывания. Получите полный контроль над своими финансовыми данными с мощными инструментами аналитики и планирования бюджета.

### ✨ Почему Hasta La Vista, Money?

- 🏠 **Self-hosted** — полный контроль над данными и инфраструктурой
- 🔓 **Open Source** — прозрачный код, свободная лицензия Apache 2.0
- 🔒 **Приватность** — ваши финансовые данные остаются только на вашем сервере
- 🚀 **Простое развертывание** — запуск в один клик через Docker Compose
- 🌐 **Поддержка русского языка** — полностью локализованный интерфейс

---

## 💡 Основные возможности

<table>
<tr>
<td width="50%">

### 💳 Финансовый учет
- Управление множественными счетами
- Поддержка различных валют
- Учет доходов и расходов
- Иерархическая категоризация
- История всех операций

### 📊 Аналитика и отчеты
- Детальная статистика по периодам
- Интерактивные графики и диаграммы
- Анализ расходов по категориям
- Экспорт данных в JSON

### 🧾 Обработка чеков
- Распознавание чеков с помощью AI
- Импорт данных через QR-коды
- Ручное добавление покупок
- Анализ по продавцам и товарам

</td>
<td width="50%">

### 📈 Бюджетирование
- Планирование доходов и расходов
- Сравнение планов с фактом
- Отслеживание выполнения бюджета
- Умные уведомления о лимитах

### 👤 Персональный профиль
- Дашборд с общей статистикой
- Детальная аналитика за 6 месяцев
- Топ категорий расходов
- Рекомендации по оптимизации

### 🔔 Система уведомлений
- Предупреждения о низком балансе
- Алерты о превышении расходов
- Поощрения за сбережения
- Персональные рекомендации

</td>
</tr>
</table>

---

## 🛠 Технологический стек

| Компонент | Технологии |
|-----------|-----------|
| **Backend** | Django 6.0, Python 3.12.7+ (Docker: Python 3.13), Django REST Framework, Celery |
| **Frontend** | Tailwind CSS 4, DaisyUI, Chart.js, jQuery, HTMX |
| **База данных** | PostgreSQL, SQLite (локальный fallback без `DATABASE_URL`/`POSTGRES_*`) |
| **Кеширование и очереди** | Redis, django-redis, django-celery-beat, LocMemCache для локального fallback |
| **API** | RESTful API, OpenAPI schema, Swagger UI |
| **Контейнеризация** | Docker, Docker Compose, Nginx, отдельный OCR/LLM-сервис для чеков |
| **Безопасность** | CSP, CSRF, JWT аутентификация, django-axes |
| **Мониторинг** | Sentry-compatible error tracking, django-structlog, Django Debug Toolbar |
| **Локализация** | i18n, полная поддержка русского языка |

---

## 🚀 Быстрый старт

### Минимальные требования
- Docker и Docker Compose
- Несколько ГБ свободного места для Docker-образов, PostgreSQL/Redis и OCR-моделей
- От 4 ГБ оперативной памяти для локального Docker-запуска; production OCR/LLM-сервисы требуют больше ресурсов

### Установка за 3 шага

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money

# 2. Создайте файл .env с минимальными локальными настройками
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

**Готово!** После сборки и запуска контейнеров откройте браузер и перейдите по адресу [http://127.0.0.1:8090](http://127.0.0.1:8090)

> 💡 **Совет:** Стандартный `docker-compose.yaml` поднимает PostgreSQL, Redis, Celery worker/beat, веб-приложение, Nginx и сервис распознавания чеков. SQLite используется только как fallback при прямом локальном запуске без `DATABASE_URL` и `POSTGRES_*`.

> 🔒 **Важно:** Блок выше описывает быстрый локальный/self-hosted запуск, а не production minimum. Для production self-hosted используйте отдельное руководство: [docs/docs/production_self_hosted.md](docs/docs/production_self_hosted.md)

### Первые шаги

1. Зарегистрируйте аккаунт администратора
2. Создайте свой первый финансовый счет
3. Добавьте категории доходов и расходов
4. Начните вести учет финансов!

> 📚 **Полная документация по установке и настройке:** [hasta-la-vista-money.readthedocs.io](https://hasta-la-vista-money.readthedocs.io/)

---

## ⚙️ Конфигурация

Приложение настраивается через переменные окружения в файле `.env`:

### Основные переменные

| Переменная | Описание | Значение по умолчанию |
|-----------|----------|----------------------|
| `SECRET_KEY` | Секретный ключ Django (обязательно) | - |
| `DJANGO_SETTINGS_MODULE` | Модуль настроек Django; для production используйте `config.django.prod` | `config.django.base` |
| `DEBUG` | Режим отладки | `false` |
| `ALLOWED_HOSTS` | Разрешенные production-хосты | - |
| `BASE_URL` | Базовый URL приложения | `http://127.0.0.1:8000/` |
| `CSRF_TRUSTED_ORIGINS` | Доверенные HTTPS-источники для CSRF | - |
| `DATABASE_URL` | URL внешней PostgreSQL, если не используется встроенный `db` из Compose | - |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Параметры встроенной PostgreSQL в `docker-compose.prod.yaml` | `hlvm`, `postgres`, `postgres` |
| `REDIS_LOCATION` | URL Redis для кеширования, сессий и Celery в production | - |
| `ERROR_TRACKING_DSN` | DSN для Sentry-compatible мониторинга ошибок | - |
| `ERROR_TRACKING_ENVIRONMENT` | Окружение для мониторинга ошибок | `production` |
| `SESSION_COOKIE_SECURE` | Флаг `Secure` для session cookie | `true` |
| `SESSION_COOKIE_HTTPONLY` | Флаг `HttpOnly` для session cookie | `true` |
| `SESSION_COOKIE_SAMESITE` | Политика `SameSite` для session cookie | `Lax` |
| `SESSION_COOKIE_AGE` | Время жизни session cookie в секундах | `31536000` |
| `CSRF_COOKIE_SECURE` | Флаг `Secure` для CSRF cookie | `true` |
| `SECURE_SSL_REDIRECT` | Принудительное перенаправление на HTTPS | `true` |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Заголовок защиты от MIME-sniffing | `true` |
| `SECURE_HSTS_SECONDS` | Значение `max-age` для HSTS | `31536000` |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | HSTS для поддоменов | `true` |
| `SECURE_HSTS_PRELOAD` | Предзагрузка HSTS | `true` |
| `ACCESS_TOKEN_LIFETIME` | Время жизни JWT access token в минутах | `60` |
| `REFRESH_TOKEN_LIFETIME` | Время жизни JWT refresh token в днях | `7` |
| `LANGUAGE_CODE` | Язык интерфейса | `ru-RU` |
| `TIME_ZONE` | Часовой пояс | `Europe/Moscow` |
| `RECEIPT_INFERENCE_URL` | URL внутреннего сервиса OCR/LLM для чеков | `http://receipt-inference:8010` |
| `RECEIPT_INFERENCE_TIMEOUT` | Таймаут обработки чеков в секундах | `420` |
| `API_KEY`, `API_MODEL`, `API_BASE_URL`, `API_TIMEOUT` | Fallback для OpenAI-compatible API, если не используется `RECEIPT_INFERENCE_URL` | - |
| `AI_RATE_LIMIT_PER_USER`, `AI_RATE_LIMIT_GLOBAL`, `AI_RATE_LIMIT_WINDOW` | Лимиты AI-обработки чеков | `10`, `100`, `60` |

### Дополнительные возможности

- **PostgreSQL**: Docker Compose поднимает PostgreSQL по умолчанию; SQLite остается fallback для прямого локального запуска
- **Redis и Celery**: Redis используется для кеша, сессий, rate limiting, django-axes и брокера/результатов Celery
- **AI для чеков**: Внутренний `receipt-inference` сервис выполняет OCR/LLM-обработку; при отсутствии `RECEIPT_INFERENCE_URL` доступен fallback на OpenAI-compatible API
- **Мониторинг ошибок**: Sentry-compatible мониторинг ошибок в production через `ERROR_TRACKING_DSN`

### Минимум для production при самостоятельном размещении

Для `docker-compose.prod.yaml` минимальный набор production-переменных включает:

- `SECRET_KEY`
- `DJANGO_SETTINGS_MODULE=config.django.prod`
- `DEBUG=false`
- `ALLOWED_HOSTS`
- `BASE_URL`
- `CSRF_TRUSTED_ORIGINS`
- `REDIS_LOCATION`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` для встроенного PostgreSQL в `docker-compose.prod.yaml`
- `DATABASE_URL`, если используется внешняя PostgreSQL вместо встроенного сервиса `db`
- переменные cookie и transport security: `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`
- `RECEIPT_INFERENCE_URL`, `RECEIPT_INFERENCE_TIMEOUT` и параметры `LLAMA_*`/`OCR_*`, если включена обработка чеков через bundled inference services
- `ERROR_TRACKING_DSN` и `ERROR_TRACKING_ENVIRONMENT`, если используется мониторинг production-окружения

Секреты не должны храниться в репозитории или поддерживаться вручную в локальном `.env` на сервере без контроля изменений. Для production-развертывания при самостоятельном размещении `.env` должен формироваться на этапе деплоя из CI/CD secrets, менеджера секретов или зашифрованной системы управления конфигурацией.

Подробный чек-лист production-развертывания: [docs/docs/production_self_hosted.md](docs/docs/production_self_hosted.md)

#### Redis — Кеширование для производительности

Redis используется в продакшене для кеширования, сессий и фоновых задач:

**Что кешируется:**

- Дерево категорий (TTL: 5 минут)
- Статистика пользователя (TTL: 10 минут)
- Список финансовых счетов (TTL: 5 минут)
- Сессии пользователей
- Rate limiting для API
- Защита от брутфорса (django-axes)
- Брокер и backend результатов Celery

**Настройка для продакшена:**

```bash
# В .env файле добавьте:
REDIS_LOCATION=redis://redis:6379/0
DEBUG=false
```

**Запуск с Redis:**

```bash
# Используйте продакшен конфигурацию
docker compose -f docker-compose.prod.yaml up -d
```

**Проверка работы Redis:**

```bash
# Подключение к Redis
docker exec -it hlvm-prod-redis-1 redis-cli ping
# Должно вернуть: PONG

# Просмотр кешированных ключей
docker exec -it hlvm-prod-redis-1 redis-cli KEYS "hlvm:*"
```

> 📘 **Подробная документация по кешированию:** [docs/docs/cache.md](docs/docs/cache.md)

> 📖 **Полный список переменных и примеры конфигурации:** [Документация по настройке](https://hasta-la-vista-money.readthedocs.io/)

---

## 🔒 Безопасность

Приложение включает множество механизмов защиты:

- ✅ Защита от CSRF и XSS атак
- ✅ Content Security Policy (CSP)
- ✅ JWT аутентификация для API
- ✅ Валидация всех входных данных
- ✅ Защита от SQL-инъекций через Django ORM
- ✅ Rate limiting для API (django-axes)
- ✅ Безопасное хранение паролей через password hashers Django
- ✅ Docker контейнеры работают от непривилегированного пользователя (appuser)
- ✅ Минимальные права доступа к файлам и директориям
- ✅ Права доступа настроены для статических файлов и логов

---

## 📚 Документация

Полная документация размещена на **[Read the Docs](https://hasta-la-vista-money.readthedocs.io/)**:

- 📖 [Руководство пользователя](https://hasta-la-vista-money.readthedocs.io/) — начало работы, функции, примеры использования
- 🛠 [Руководство разработчика](https://hasta-la-vista-money.readthedocs.io/contribute/) — архитектура, разработка, тестирование
- 🔌 [API документация](https://hasta-la-vista-money.readthedocs.io/api/) — REST API, эндпоинты, примеры запросов

В запущенном приложении также доступны:

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/schema/swagger-ui/`
- Экспорт схемы в документацию: `make export-api-schema`

---

## 🤝 Участие в разработке

Мы приветствуем любой вклад в проект! Вот как вы можете помочь:

### Способы участия

- 🐛 **Сообщить о баге** — создайте [Issue](https://github.com/TurtleOld/hasta-la-vista-money/issues)
- 💡 **Предложить улучшение** — опишите свою идею в [Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions)
- 🔧 **Исправить проблему** — создайте Pull Request
- 📝 **Улучшить документацию** — docs всегда нуждаются в обновлениях
- 🌍 **Добавить перевод** — помогите локализовать приложение

### Процесс разработки

```bash
# 1. Форкните и клонируйте репозиторий
git clone https://github.com/YOUR_USERNAME/hasta-la-vista-money.git

# 2. Создайте ветку для новой функции
git checkout -b feature/amazing-feature

# 3. Установите зависимости для разработки
make install

# 4. Внесите изменения и протестируйте
make test

# 5. Создайте Pull Request
```

### ⚠️ Важная информация о uv.lock

**`uv.lock` не хранится в репозитории!** Этот файл генерируется автоматически:

- **В GitHub Actions:** при сборке Docker образов
- **В Docker:** если файл отсутствует, он создается автоматически
- **Локальная разработка:** генерируется командой `make install` или `uv sync --dev`

Причины такого подхода:
- ✅ Избежание конфликтов при работе в команде
- ✅ Автоматическая генерация для разных платформ (linux/amd64, linux/arm64)
- ✅ Чистый репозиторий без больших lock-файлов
- ✅ Воспроизводимость через `pyproject.toml`

**Для локальной разработки:**
```bash
# При первом запуске генерируется uv.lock автоматически
make install

# Если нужно обновить зависимости:
uv lock --upgrade
```

> 📋 **Подробнее:** [Руководство контрибьютора](https://hasta-la-vista-money.readthedocs.io/contribute/)

---

## 💬 Сообщество и поддержка

- 💬 [GitHub Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions) — обсуждения, вопросы, идеи
- 🐛 [Issue Tracker](https://github.com/TurtleOld/hasta-la-vista-money/issues) — баги и запросы на функции
- 📧 [Email](mailto:dev@pavlovteam.ru) — прямая связь с разработчиком

---

## 📄 Лицензия

Проект распространяется под лицензией **Apache License 2.0**.
См. файл [LICENSE](LICENSE) для подробностей.

```
Copyright 2022-2025 Alexander Pavlov (TurtleOld)
Licensed under the Apache License, Version 2.0
```

---

## ⭐ Поддержите проект

Если вам нравится **Hasta La Vista, Money!**, поставьте ⭐ на GitHub!
Это помогает другим пользователям найти проект.

---

<div align="center">

**Hasta La Vista, Money!** — ваш надежный помощник в управлении личными финансами! 💪

[📖 Документация](https://hasta-la-vista-money.readthedocs.io/) • [🐛 Баг-репорты](https://github.com/TurtleOld/hasta-la-vista-money/issues)

</div>
