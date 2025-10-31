# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Codacy Coverage](https://app.codacy.com/project/badge/Coverage/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_coverage)
[![Lines of Code](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)

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
| **Backend** | Django 5.2, Python 3.12, Django REST Framework |
| **Frontend** | Bootstrap 5, Chart.js, jQuery, HTMX |
| **База данных** | PostgreSQL, SQLite (для разработки) |
| **API** | RESTful API, OpenAPI/Swagger документация |
| **Контейнеризация** | Docker, Docker Compose |
| **Безопасность** | CSP, CSRF, JWT аутентификация, django-axes |
| **Мониторинг** | Sentry, Django Debug Toolbar |
| **Локализация** | i18n, полная поддержка русского языка |

---

## 🚀 Быстрый старт

### Минимальные требования
- Docker и Docker Compose
- 1 ГБ свободного места на диске
- 512 МБ оперативной памяти

### Установка за 3 шага

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money

# 2. Создайте файл .env с минимальными настройками
cat > .env << EOF
SECRET_KEY=$(openssl rand -base64 50)
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1
EOF

# 3. Запустите приложение
docker compose up -d
```

**Готово!** Откройте браузер и перейдите по адресу [http://127.0.0.1:8090](http://127.0.0.1:8090)

> 💡 **Совет:** При первом запуске приложение автоматически создаст SQLite базу данных. Для production рекомендуется использовать PostgreSQL.

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
| `DEBUG` | Режим отладки | `false` |
| `ALLOWED_HOSTS` | Разрешенные хосты | `localhost,127.0.0.1` |
| `DATABASE_URL` | URL PostgreSQL (опционально) | SQLite |
| `LANGUAGE_CODE` | Язык интерфейса | `ru-RU` |
| `TIME_ZONE` | Часовой пояс | `Europe/Moscow` |

### Дополнительные возможности

- **PostgreSQL**: Для production рекомендуется PostgreSQL вместо SQLite
- **AI для чеков**: Интеграция с OpenAI API для автоматического распознавания чеков
- **Sentry**: Мониторинг ошибок в production
- **Redis**: Кэширование для повышения производительности

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
- ✅ Безопасное хранение паролей (bcrypt)
- ✅ Docker контейнеры работают от непривилегированного пользователя (appuser)
- ✅ Минимальные права доступа к файлам и директориям
- ✅ Права доступа настроены для статических файлов и логов

---

## 📚 Документация

Полная документация размещена на **[Read the Docs](https://hasta-la-vista-money.readthedocs.io/)**:

- 📖 [Руководство пользователя](https://hasta-la-vista-money.readthedocs.io/) — начало работы, функции, примеры использования
- 🛠 [Руководство разработчика](https://hasta-la-vista-money.readthedocs.io/contribute/) — архитектура, разработка, тестирование
- 🔌 [API документация](https://hasta-la-vista-money.readthedocs.io/api/) — REST API, эндпоинты, примеры запросов

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
uv sync --dev

# 4. Внесите изменения и протестируйте
uv run pytest

# 5. Создайте Pull Request
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
