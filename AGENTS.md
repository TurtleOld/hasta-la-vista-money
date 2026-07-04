# AGENTS.md - Руководство для AI-агентов

Этот документ содержит важную информацию для AI-агентов, работающих с проектом **Hasta La Vista, Money!** — системой управления личными финансами на Django.

---

## 📋 О проекте

**Hasta La Vista, Money!** — это Django-приложение для управления личными финансами с открытым исходным кодом. Проект использует современные практики разработки, включая dependency injection, репозиторный паттерн, и RESTful API.

### Технологический стек

- **Backend**: Django 6.0, Python 3.12
- **API**: Django REST Framework (DRF)
- **База данных**: PostgreSQL (продакшен), SQLite (разработка)
- **Кеширование**: Redis (продакшен), LocMemCache (разработка)
- **Аутентификация**: JWT (djangorestframework-simplejwt)
- **Dependency Injection**: dependency-injector
- **Чеки**: QR-flow через интеграцию с API ФНС
- **Frontend**: Bootstrap 5, Chart.js, jQuery, HTMX

Для обработки чеков через ФНС должны быть заданы:
`FNS_INN`, `FNS_PASSWORD`, `FNS_CLIENT_SECRET`.

---

## 🏗 Архитектура проекта

### Структура приложений

Проект организован в виде Django-приложений, каждое из которых отвечает за определенную функциональность:

```
hasta_la_vista_money/
├── api/                    # REST API эндпоинты
├── authentication/         # JWT аутентификация
├── budget/                 # Бюджетирование и планирование
├── expense/                # Управление расходами
├── finance_account/        # Финансовые счета
├── income/                 # Управление доходами
├── loan/                   # Кредиты и займы
├── receipts/               # Обработка чеков (QR + ФНС)
├── reports/                # Отчеты и аналитика
├── users/                  # Управление пользователями
└── core/                   # Общие компоненты
```

### Архитектурные паттерны

#### 1. Dependency Injection (DI)

Проект использует `dependency-injector` для управления зависимостями. Основной контейнер находится в `config/containers.py`:

```python
# Пример использования в view
class MyView(APIView):
    def post(self, request):
        container = request.container
        expense_service = container.expense.expense_service()
        # Использование сервиса
```

**Важно:**
- Все сервисы регистрируются в контейнерах приложений
- Репозитории создаются как Singleton
- Сервисы создаются как Factory
- Контейнер доступен через `request.container` (настроено в middleware)

#### 2. Repository Pattern

Каждое приложение имеет папку `repositories/` с классами для работы с базой данных:

```python
# Пример репозитория
class ExpenseRepository:
    def get_by_user(self, user: User) -> QuerySet[Expense]:
        return Expense.objects.filter(user=user)
```

**Правила:**
- Репозитории НЕ содержат бизнес-логику
- Только работа с ORM и базой данных
- Всегда возвращают QuerySet или объекты моделей

#### 3. Service Layer

Бизнес-логика находится в сервисах (`services/`):

```python
# Пример сервиса
class ExpenseService:
    def __init__(
        self,
        expense_repository: ExpenseRepository,
        account_service: AccountServiceProtocol,
    ):
        self.expense_repository = expense_repository
        self.account_service = account_service

    def create_expense(self, data: dict) -> Expense:
        # Бизнес-логика создания расхода
        pass
```

**Правила:**
- Сервисы содержат всю бизнес-логику
- Сервисы используют репозитории и другие сервисы
- Сервисы регистрируются в контейнерах через протоколы

#### 4. Protocol-based Design

Проект использует протоколы (Protocol) для определения интерфейсов:

```python
# Пример протокола
class ExpenseServiceProtocol(Protocol):
    def create_expense(self, data: dict) -> Expense:
        ...
```

**Правила:**
- Протоколы определяются в `protocols/`
- Сервисы реализуют протоколы
- DI контейнеры используют протоколы для типизации

---

## 📝 Правила кодирования

### Стиль кода

1. **Python стиль:**
   - PEP 8 compliance
   - Использование `ruff` для линтинга
   - Максимальная длина строки: 80 символов
   - Использование одинарных кавычек (`'`) для строк

2. **Django конвенции:**
   - Class-based views для сложной логики
   - Function-based views для простых случаев
   - Использование Django ORM вместо raw SQL
   - Следование MVT паттерну

3. **Типизация:**
   - Использование type hints везде
   - Строгий режим mypy (`strict = true`)
   - Использование `Final` для констант

### Именование

- **Классы**: PascalCase (`ExpenseService`, `ExpenseRepository`)
- **Функции/методы**: snake_case (`create_expense`, `get_by_user`)
- **Константы**: UPPER_SNAKE_CASE (`PAGINATE_BY_DEFAULT`, `SUCCESS_CODE`)
- **Переменные**: snake_case (`expense_data`, `user_account`)

### Импорты

Используется `isort` для сортировки импортов. Порядок:
1. Стандартная библиотека
2. Django
3. Сторонние библиотеки
4. Локальные импорты (`hasta_la_vista_money`)

### Константы

Все константы определены в `hasta_la_vista_money/constants.py`:
- Используйте константы вместо магических чисел/строк
- Добавляйте новые константы в этот файл
- Используйте `Final` для типизации

---

## 🔧 Работа с кодом

### Создание нового сервиса

1. Создайте протокол в `app/protocols/services.py`:
```python
class MyServiceProtocol(Protocol):
    def do_something(self, data: dict) -> Result:
        ...
```

2. Создайте реализацию в `app/services/my_service.py`:
```python
class MyService:
    def __init__(self, repository: MyRepository):
        self.repository = repository

    def do_something(self, data: dict) -> Result:
        # Логика
        pass
```

3. Зарегистрируйте в контейнере `app/containers.py`:
```python
class MyContainer(containers.DeclarativeContainer):
    my_repository = providers.Singleton(MyRepository)

    my_service: providers.Factory[MyServiceProtocol] = providers.Factory(
        MyService,
        repository=my_repository,
    )
```

### Создание нового API эндпоинта

1. Используйте DRF для всех API:
```python
class MyAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        container = request.container
        service = container.my_app.my_service()
        result = service.get_data()
        return Response(result)
```

2. Зарегистрируйте в `app/urls.py`:
```python
path('api/my-endpoint/', MyAPIView.as_view(), name='my_endpoint'),
```

**Важно:**
- Все API должны быть через DRF, не через function-based views
- Используйте версионирование: `/api/v1/...`
- Всегда добавляйте аутентификацию и throttling

### Работа с моделями

```python
class MyModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]
```

**Правила:**
- Всегда добавляйте индексы для часто используемых полей
- Используйте `select_related` и `prefetch_related` для оптимизации запросов
- Не добавляйте бизнес-логику в модели (используйте сервисы)

### Работа с формами

```python
class MyForm(forms.ModelForm):
    class Meta:
        model = MyModel
        fields = ['field1', 'field2']
        widgets = {
            'field1': forms.TextInput(attrs={'class': 'form-control'}),
        }
```

**Правила:**
- Используйте ModelForm для форм, связанных с моделями
- Используйте crispy-forms для Bootstrap стилизации
- Валидация должна быть в форме, не в view

---

## 🧪 Тестирование

### Структура тестов

Тесты находятся в `app/tests/`:
- `test_models.py` - тесты моделей
- `test_views.py` - тесты views
- `test_services.py` - тесты сервисов
- `test_repositories.py` - тесты репозиториев

### Написание тестов

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()

class ExpenseServiceTest(TestCase):
    def test_create_expense(self) -> None:
        user = User.objects.create_user(username='test-user')
        container = ApplicationContainer()
        service = container.expense.expense_service()
        # Тест логики
```

**Правила:**
- Используйте стандартные `django.test.TestCase` / `TransactionTestCase`
- В проекте используется только unittest, без pytest: никаких голых `assert` в тестах — только методы `self.assert*` (для сужения типов вместо `assert x is not None` используйте `if x is None: self.fail(...)`)
- Запускайте тесты через `python manage.py test`
- Покрытие тестами должно быть не менее 85%
- Используйте фикстуры для общих данных
- Тестируйте сервисы, а не только views

---

## 🔐 Безопасность

### Аутентификация

- JWT токены для API (`djangorestframework-simplejwt`)
- Session-based аутентификация для веб-интерфейса
- Всегда проверяйте `IsAuthenticated` для защищенных эндпоинтов

### Валидация данных

- Всегда валидируйте входные данные
- Используйте Django forms для валидации
- Используйте DRF serializers для API
- Никогда не доверяйте пользовательскому вводу

### Защита от атак

- CSRF защита включена по умолчанию
- CSP (Content Security Policy) настроен
- Rate limiting через `django-axes` и DRF throttling
- SQL injection защита через Django ORM

---

## 🚀 Запуск и разработка

### Установка зависимостей

```bash
# Устанавливает Python-зависимости, Node-зависимости и собирает JS
make install
```

### Запуск проекта

```bash
# Разработка
make start

# Продакшен
docker compose -f docker-compose.prod.yaml up -d
```

### Миграции

```bash
make migrate
```

### Статические файлы

```bash
make staticfiles
```

### JavaScript-сборка (esbuild)

**После любых изменений в JS-файлах необходимо выполнить сборку:**

```bash
# Однократная сборка всех бандлов
make build-js

# Режим наблюдения (пересборка при изменениях)
make watch-js
```

Esbuild собирает несколько entry points в `static/js/dist/`:

| Entry point | Выходной файл | Загружается на |
|---|---|---|
| `static/js/app.js` | `dist/app.js` | Все страницы |
| `static/js/pages/dashboard.js` | `dist/pages/dashboard.js` | Дашборд |
| `static/js/pages/budget.js` | `dist/pages/budget.js` | Бюджет |
| `static/js/pages/receipts.js` | `dist/pages/receipts.js` | Список чеков |
| `static/js/pages/receipt-update.js` | `dist/pages/receipt-update.js` | Редактирование чека |
| `static/js/pages/loan.js` | `dist/pages/loan.js` | Кредиты |
| `static/js/pages/profile.js` | `dist/pages/profile.js` | Профиль |

**Важно:**
- `static/js/dist/` исключён из `.gitignore` и `.dockerignore` — файлы не хранятся в репозитории
- В production Docker-образе JS собирается автоматически в `node-builder` stage
- В локальной разработке Django-сервер читает уже собранные файлы — после изменений нужно вручную запустить `make build-js` (или держать открытым `make watch-js`)
- Исходники для page-specific бандлов — в `static/js/pages/`, они импортируют файлы из `static/js/`

---

## 📚 Важные файлы и директории

### Конфигурация

- `config/django/base.py` - основные настройки Django
- `config/django/prod.py` - настройки для продакшена
- `config/containers.py` - главный DI контейнер
- `config/urls.py` - главный URL конфиг

### Общие компоненты

- `hasta_la_vista_money/constants.py` - все константы проекта
- `core/` - общие компоненты (views, mixins, types)
- `core/protocols/` - общие протоколы

### Middleware

- `hasta_la_vista_money/compressor_middleware.py` - сжатие ответов
- `config/middleware.py` - настройка DI контейнера для request

---

## 🎯 Специфичные правила проекта

### 1. Использование констант

**Всегда** используйте константы из `constants.py`:
```python
# ❌ Плохо
paginate_by = 10

# ✅ Хорошо
from hasta_la_vista_money.constants import PAGINATE_BY_DEFAULT
paginate_by = PAGINATE_BY_DEFAULT
```

### 2. Работа с DI контейнером

**Всегда** получайте сервисы через контейнер:
```python
# ❌ Плохо
service = ExpenseService(repository)

# ✅ Хорошо
container = request.container
service = container.expense.expense_service()
```

### 3. Локализация

Все пользовательские сообщения должны быть локализованы:
```python
from django.utils.translation import gettext_lazy as _

message = _('Операция успешно создана!')
```

### 4. Обработка ошибок

Используйте try-except для обработки ошибок:
```python
try:
    result = service.create_expense(data)
except ValidationError as e:
    return Response({'error': str(e)}, status=400)
```

### 5. Кеширование

Используйте Django cache framework:
```python
from django.core.cache import cache

cache_key = f'user_{user.id}_expenses'
cached_data = cache.get(cache_key)
if not cached_data:
    cached_data = expensive_operation()
    cache.set(cache_key, cached_data, timeout=300)
```

---

## 🔍 Поиск и навигация по коду

### Где искать код

- **Модели**: `app/models.py`
- **Views**: `app/views.py` (HTML), `app/apis.py` (API)
- **Сервисы**: `app/services/`
- **Репозитории**: `app/repositories/`
- **Протоколы**: `app/protocols/`
- **Контейнеры DI**: `app/containers.py`
- **URLs**: `app/urls.py`
- **Шаблоны**: `app/templates/app/`
- **Статика**: `static/`

### Типичные задачи

1. **Добавить новую функциональность:**
   - Создать модель → миграцию → репозиторий → сервис → view → URL → шаблон

2. **Исправить баг:**
   - Найти соответствующий сервис/view → понять логику → исправить → добавить тест

3. **Оптимизировать запрос:**
   - Проверить использование `select_related`/`prefetch_related` → добавить индексы → использовать кеш

---

## ⚠️ Частые ошибки и как их избежать

1. **Дублирование кода:**
   - Используйте базовые классы и миксины
   - Выносите общую логику в сервисы

2. **N+1 запросы:**
   - Всегда используйте `select_related` для ForeignKey
   - Используйте `prefetch_related` для ManyToMany и reverse ForeignKey

3. **Отсутствие валидации:**
   - Всегда валидируйте данные в формах/serializers
   - Используйте Django validators

4. **Хардкод значений:**
   - Используйте константы из `constants.py`
   - Используйте настройки Django для конфигурации

5. **Игнорирование типизации:**
   - Всегда добавляйте type hints
   - Используйте протоколы для интерфейсов

---

## 🌿 Правила именования веток

AI-агенты должны создавать ветки только по предсказуемому формату,
совместимому с Conventional Commits и Release Please:

```
<type>/<scope>-<short-description>
```

**Правила:**
- `type` должен быть одним из типов Conventional Commits: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`
- `scope` должен отражать приложение или область изменений: `finance_account`, `receipts`, `expense`, `income`, `loan`, `budget`, `api`, `auth`, `commands`, `ci`, `release`
- `short-description` пишется на английском, в lowercase kebab-case
- В названии ветки запрещены пробелы, заглавные буквы, подчёркивания, кириллица и произвольные разделители
- Название ветки должно отражать суть задачи, а не быть произвольным заголовком или дословной фразой пользователя

**Примеры:**
```bash
# ✅ Правильно
fix/transactions-static-mobile-layout
refactor/commands-service-protocols
feat/receipts-qr-validation
ci/release-please-title-check

# ❌ Неправильно
Refactor/service protocols commands
fix transactions layout
some-random-branch
правка-чеков
```

При создании веток через Agent Manager или другие инструменты агент обязан
использовать этот же формат в `branchName`.

---

## 📝 Правила коммитов (Conventional Commits)

Проект использует [Conventional Commits](https://www.conventionalcommits.org/) для автоматического управления версиями через **Release Please**.

### Формат коммита

```
<type>(<scope>): <description>
```

**Важно:** тип и описание — строчными буквами, двоеточие обязательно. Release Please **игнорирует** коммиты без этого формата.

### Типы коммитов

| Тип | Описание | Влияние на версию |
|---|---|---|
| `feat` | Новая функциональность | MINOR (2.1.0 → 2.2.0) |
| `fix` | Исправление бага | PATCH (2.1.0 → 2.1.1) |
| `chore` | Обслуживание, зависимости | нет |
| `docs` | Документация | нет |
| `test` | Тесты | нет |
| `refactor` | Рефакторинг без новой функциональности | нет |
| `perf` | Оптимизация производительности | нет |
| `ci` | Изменения CI/CD | нет |

Для **BREAKING CHANGE** (MAJOR) добавляйте `!` после типа: `feat!: ...` или указывайте `BREAKING CHANGE:` в теле коммита.

### Примеры

```bash
# ✅ Правильно
git commit -m "fix(sberbank): correct grace period debt calculation"
git commit -m "feat(receipts): add QR code validation"
git commit -m "fix: prevent negative balance on account withdrawal"

# ❌ Неправильно — Release Please проигнорирует
git commit -m "Fix Sberbank grace period debt calculation"
git commit -m "Fixed bug in receipts"
git commit -m "FEAT: add new feature"
```

### Scope (необязательный, но рекомендуемый)

Используйте название Django-приложения: `finance_account`, `receipts`, `expense`, `income`, `loan`, `budget`, `api`, `auth`.

### Если коммит не попал в Release Please PR

Если коммит был смерджен без правильного формата и не появился в Release Please PR — добавьте пустой коммит с корректным сообщением:

```bash
git commit --allow-empty -m "fix(sberbank): correct grace period debt calculation"
git push
```

Release Please подхватит его при следующем запуске и обновит PR с changelog.

---

## 📖 Дополнительные ресурсы

- [Документация проекта](https://hasta-la-vista-money.readthedocs.io/)
- [Django документация](https://docs.djangoproject.com/)
- [DRF документация](https://www.django-rest-framework.org/)
- [Dependency Injector документация](https://python-dependency-injector.ets-labs.org/)

---

## 🎓 Примеры кода

### Полный пример создания нового функционала

```python
# 1. Протокол (app/protocols/services.py)
class MyFeatureServiceProtocol(Protocol):
    def process(self, data: dict) -> Result:
        ...

# 2. Модель (app/models.py)
class MyFeature(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

# 3. Репозиторий (app/repositories/my_feature_repository.py)
class MyFeatureRepository:
    def get_by_user(self, user: User) -> QuerySet[MyFeature]:
        return MyFeature.objects.filter(user=user)

# 4. Сервис (app/services/my_feature_service.py)
class MyFeatureService:
    def __init__(
        self,
        repository: MyFeatureRepository,
    ):
        self.repository = repository

    def process(self, data: dict) -> Result:
        # Бизнес-логика
        return result

# 5. Контейнер (app/containers.py)
class MyAppContainer(containers.DeclarativeContainer):
    my_feature_repository = providers.Singleton(MyFeatureRepository)

    my_feature_service: providers.Factory[MyFeatureServiceProtocol] = (
        providers.Factory(
            MyFeatureService,
            repository=my_feature_repository,
        )
    )

# 6. API View (app/apis.py)
class MyFeatureAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request):
        container = request.container
        service = container.my_app.my_feature_service()
        result = service.process(request.data)
        return Response(result, status=201)

# 7. URL (app/urls.py)
path('api/v1/my-feature/', MyFeatureAPIView.as_view(), name='my_feature'),
```

---
