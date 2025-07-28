# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)
[![](https://app.codacy.com/project/badge/Grade/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![](https://app.codacy.com/project/badge/Coverage/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_coverage)
[![](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=blanks)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=blanks)
[![](https://wakatime.com/badge/github/TurtleOld/hasta-la-vista-money.svg)](https://wakatime.com/badge/github/TurtleOld/hasta-la-vista-money)

**[🇺🇸 English version](ENGLISH.md)**

## 🎯 О проекте

**Hasta La Vista, Money!** — это современная система управления личными финансами, разработанная как self-hosted open source решение для эффективного учета доходов, расходов и планирования бюджета. Приложение предоставляет полный набор инструментов для контроля финансового состояния с интуитивно понятным интерфейсом и сильной аналитикой.

**Ключевые особенности:**
- 🏠 **Self-hosted** — полный контроль над данными и инфраструктурой
- 🔓 **Open Source** — прозрачный код и возможность кастомизации
- 🔒 **Приватность** — ваши финансовые данные остаются на вашем сервере

### ✨ Ключевые возможности

#### 💳 **Управление счетами**
- Создание и управление множественными счетами
- Поддержка различных валют
- Автоматический расчет общего баланса
- История операций по каждому счету

#### 📊 **Учет доходов и расходов**
- Категоризация доходов и расходов
- Иерархическая структура категорий
- Быстрое добавление операций
- Фильтрация и поиск по датам, категориям, суммам

#### 🧾 **Обработка чеков**
- Автоматическое распознавание чеков
- Ручное добавление покупок
- Анализ покупок по продавцам и товарам

#### 📈 **Бюджетирование и планирование**
- Месячное планирование доходов и расходов
- Сравнение планов с фактическими данными
- Отслеживание выполнения бюджета
- Уведомления о превышении лимитов

#### 📋 **Отчеты и аналитика**
- Детальная статистика по периодам
- Графики динамики доходов и расходов
- Анализ по категориям
- Экспорт данных в JSON формате

#### 👤 **Персональный профиль**
- **Дашборд статистики**: общий баланс, месячные доходы/расходы, сбережения
- **Система вкладок**: персональная информация, статистика, последние операции, настройки
- **Детальная аналитика**: графики за 6 месяцев, топ категорий, процент сбережений
- **Умные уведомления**: предупреждения о низком балансе, превышении расходов, рекомендации
- **Экспорт данных**: полный выгруз всех данных пользователя

#### 🔔 **Система уведомлений**
- Автоматические уведомления о важных событиях
- Предупреждения о низком балансе счетов
- Уведомления о превышении расходов над доходами
- Поощрения за хорошие сбережения
- Рекомендации по улучшению финансового состояния

### 🛠 Технологический стек

- **Backend**: Django 5.2, Python 3.12
- **Frontend**: Bootstrap 5, Chart.js, jQuery
- **База данных**: PostgreSQL
- **Контейнеризация**: Docker & Docker Compose
- **Безопасность**: CSP, CSRF защита, аутентификация
- **Интернационализация**: Поддержка русского языка

### 🚀 Быстрый старт

#### Требования
- Docker и Docker Compose
- PostgreSQL (опционально, можно использовать SQLite для разработки)

#### Установка

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money
```

2. **Создайте файл `.env` в корне проекта:**
```bash
# Обязательные настройки
SECRET_KEY=your-secret-key-here 
# Создать ключ можно командой: make secretkey
DEBUG=false
DATABASE_URL=postgres://username:password@localhost:5432/hasta_la_vista_money
# Можно не указывать, только создаться SQLite база.
ALLOWED_HOSTS=localhost,127.0.0.1
# В production среде необходимо указать домен.
```

3. **Запустите приложение:**
```bash
docker compose up -d
```

4. **Откройте браузер и перейдите по адресу:**
```
http://127.0.0.1:8090
```

5. **Создайте аккаунт:**
- Перейдите на страницу регистрации
- Заполните форму регистрации
- Готово! Теперь у вас есть полный доступ ко всем функциям системы

### 📱 Основные функции

#### 🎯 **Полный функционал для управления финансами:**
- ✅ Регистрация и аутентификация
- ✅ Управление личным профилем с расширенной аналитикой
- ✅ Добавление и редактирование счетов
- ✅ Учет доходов и расходов
- ✅ Категоризация операций
- ✅ Планирование бюджета
- ✅ Анализ финансового состояния
- ✅ Экспорт данных
- ✅ Получение уведомлений и рекомендаций
- ✅ Обработка чеков и QR-кодов
- ✅ Детальная статистика и отчеты
- ✅ Управление системой (мониторинг, настройки, резервное копирование)

### 🔧 Конфигурация

#### Переменные окружения

# Переменные окружения

## Обязательные переменные

| Переменная         | Описание                                      | Пример/Значение по умолчанию           | Обязательна? |
|--------------------|-----------------------------------------------|----------------------------------------|--------------|
| `SECRET_KEY`       | Секретный ключ Django                         | `base64 /dev/urandom \| head -c50`     | Да           |
| `DEBUG`            | Режим отладки                                 | `false` (продакшн) / `true` (dev)      | Да           |
| `ALLOWED_HOSTS`    | Разрешённые хосты через запятую               | `localhost,127.0.0.1`                  | Да           |

### Для PostgreSQL (если используется, иначе не нужны):

| Переменная         | Описание                                      | Пример/Значение по умолчанию           | Обязательна? |
|--------------------|-----------------------------------------------|----------------------------------------|--------------|
| `DATABASE_URL`     | URL базы данных (PostgreSQL)                  | `postgres://user:pass@localhost:5432/db` | Да (если не SQLite) |
| `POSTGRES_DB`      | Имя БД (альтернатива DATABASE_URL)            | `postgres`                             | Нет          |
| `POSTGRES_USER`    | Пользователь БД                               | `postgres`                             | Нет          |
| `POSTGRES_PASSWORD`| Пароль БД                                     | `postgres`                             | Нет          |
| `POSTGRES_HOST`    | Хост БД                                       | `localhost`                            | Нет          |
| `POSTGRES_PORT`    | Порт БД                                       | `5432`                                 | Нет          |

## Опциональные переменные

| Переменная                | Описание                                      | Пример/Значение по умолчанию           | Обязательна? |
|---------------------------|-----------------------------------------------|----------------------------------------|--------------|
| `BASE_URL`                | Базовый URL сайта                             | `http://127.0.0.1:8000/`               | Нет          |
| `CSRF_TRUSTED_ORIGINS`    | Доверенные origin для CSRF                    | `https://example.com`                  | Нет          |
| `LOCAL_IPS`               | Локальные IP для INTERNAL_IPS                 | `127.0.0.1`                            | Нет          |
| `LANGUAGE_CODE`           | Язык интерфейса                               | `ru-RU`                                | Нет          |
| `TIME_ZONE`               | Часовой пояс                                  | `Europe/Moscow`                        | Нет          |
| `SENTRY_DSN`              | DSN для Sentry                                | `<dsn>`                                | Нет          |
| `SENTRY_ENVIRONMENT`      | Окружение для Sentry                          | `production`                           | Нет          |
| `SENTRY_ENDPOINT`         | report_uri для CSP                            | `<url>`                                | Нет          |
| `URL_CSP_SCRIPT_SRC`      | Доп. источники для CSP                        | `https://mycdn.com`                    | Нет          |
| `SESSION_COOKIE_AGE`      | Время жизни cookie сессии (сек)               | `31536000`                             | Нет          |
| `SESSION_COOKIE_HTTPONLY` | HttpOnly для cookie сессии                    | `True`                                 | Нет          |
| `SESSION_COOKIE_NAME`     | Имя cookie сессии                             | `sessionid`                            | Нет          |
| `SESSION_COOKIE_SAMESITE` | SameSite для cookie сессии                    | `Lax`                                  | Нет          |
| `SESSION_COOKIE_SECURE`   | Secure для cookie сессии                      | `False`                                | Нет          |
| `SECURE_SSL_REDIRECT`     | Принудительный HTTPS                          | `True`                                 | Нет          |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Защита от MIME sniffing                   | `True`                                 | Нет          |
| `ACCESS_TOKEN_LIFETIME`   | Время жизни access-токена (минуты)            | `60`                                   | Нет          |
| `REFRESH_TOKEN_LIFETIME`  | Время жизни refresh-токена (дни)              | `7`                                    | Нет          |
| `DEBUG_TOOLBAR_ENABLED`   | Включить Debug Toolbar                        | `True`                                 | Нет          |

### Для интеграции с AI (чтение чеков):

| Переменная         | Описание                                      | Пример/Значение по умолчанию           | Обязательна? |
|--------------------|-----------------------------------------------|----------------------------------------|--------------|
| `API_BASE_URL`     | Базовый URL для AI-сервиса                    | `https://models.github.ai/inference`   | Нет          |
| `API_KEY`          | Ключ доступа к AI-сервису                     | `<token>`                              | Нет (но нужен для работы AI) |
| `API_MODEL`        | Модель для AI                                 | `openai/gpt-4o`                        | Нет          |

## Пример .env

```env
# Обязательные
SECRET_KEY=your-secret-key-here
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1

# Для PostgreSQL (если не SQLite)
DATABASE_URL=postgres://username:password@localhost:5432/hasta_la_vista_money

# Опциональные
BASE_URL=http://127.0.0.1:8000/
LANGUAGE_CODE=ru-RU
TIME_ZONE=Europe/Moscow
SENTRY_DSN=
SENTRY_ENVIRONMENT=
SENTRY_ENDPOINT=
URL_CSP_SCRIPT_SRC=
SESSION_COOKIE_AGE=31536000
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_NAME=sessionid
SESSION_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=True
SECURE_CONTENT_TYPE_NOSNIFF=True
ACCESS_TOKEN_LIFETIME=60
REFRESH_TOKEN_LIFETIME=7
DEBUG_TOOLBAR_ENABLED=True

# Для AI
API_BASE_URL=https://models.github.ai/inference
API_KEY=
API_MODEL=openai/gpt-4o
```

### 📊 Мониторинг и аналитика

Приложение предоставляет встроенные инструменты для мониторинга:
- Логирование всех операций
- Отслеживание производительности
- Мониторинг ошибок
- Статистика использования

### 🔒 Безопасность

- Защита от CSRF атак
- Content Security Policy (CSP)
- Безопасная аутентификация
- Валидация всех входных данных
- Защита от SQL-инъекций

### 📚 Документация

Подробная документация доступна на [Read the Docs](https://hasta-la-vista-money.readthedocs.io/):
- [Руководство пользователя](https://hasta-la-vista-money.readthedocs.io/)
- [Руководство разработчика](https://hasta-la-vista-money.readthedocs.io/contribute/)
- [API документация](https://hasta-la-vista-money.readthedocs.io/api/)

### 🤝 Участие в разработке

Мы приветствуем вклад в развитие проекта! Если вы хотите помочь:

1. Форкните репозиторий
2. Создайте ветку для новой функции
3. Внесите изменения
4. Создайте Pull Request

Подробнее о процессе разработки читайте в [руководстве контрибьютора](https://hasta-la-vista-money.readthedocs.io/contribute/).

### 📄 Лицензия

Проект распространяется под лицензией Apache 2.0. См. файл [LICENSE](LICENSE) для подробностей.

---

**Hasta La Vista, Money!** — ваш надежный помощник в управлении личными финансами! 💪
