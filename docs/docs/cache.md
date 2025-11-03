# Кеширование в Hasta La Vista, Money!

## Обзор

Проект использует многоуровневую стратегию кеширования для повышения производительности и снижения нагрузки на базу данных. В зависимости от окружения используются разные бэкенды кеша:

- **Разработка (DEBUG=True)**: LocMemCache (локальный кеш в памяти)
- **Продакшен (DEBUG=False)**: Redis (распределённый кеш)

## Конфигурация Redis

### Docker Compose

Redis настроен в обоих docker-compose файлах:

**Локальная разработка** (`docker-compose.yaml`):
```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
```

**Продакшен** (`docker-compose.prod.yaml`):
```yaml
redis:
  image: redis:latest
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
```

### Переменные окружения

Для работы Redis в продакшене необходимо установить переменную окружения:

```bash
REDIS_LOCATION=redis://redis:6379/0
```

Где:
- `redis` - имя сервиса в docker-compose
- `6379` - порт Redis
- `0` - номер базы данных Redis

### Настройки Django

Конфигурация кеша в `config/django/base.py`:

```python
if DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
            'TIMEOUT': 300,
            'OPTIONS': {
                'MAX_ENTRIES': 1000,
            },
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': config('REDIS_LOCATION', cast=str),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'CONNECTION_POOL_KWARGS': {'max_connections': 50},
                'SOCKET_CONNECT_TIMEOUT': 5,
                'SOCKET_TIMEOUT': 5,
            },
            'KEY_PREFIX': 'hlvm',
            'TIMEOUT': 300,
        },
    }
```

## Что кешируется

### 1. Дерево категорий

**Модуль**: `hasta_la_vista_money/services/views.py`

**Функция**: `get_cached_category_tree()`

**Ключ кеша**: `category_tree_{category_type}_{user_id}_{depth}`

**TTL**: 300 секунд (5 минут)

**Описание**: Кешируется иерархическая структура категорий доходов/расходов для каждого пользователя.

**Пример использования**:
```python
from hasta_la_vista_money.services.views import get_cached_category_tree

categories = get_cached_category_tree(
    user_id=user.id,
    category_type='expense',
    categories=expense_categories,
    depth=3
)
```

**Инвалидация**: Кеш автоматически истекает через 5 минут. При создании/обновлении категорий рекомендуется явно инвалидировать кеш:

```python
from django.core.cache import cache

cache.delete(f'category_tree_expense_{user.id}_3')
```

### 2. Статистика пользователя

**Модуль**: `hasta_la_vista_money/users/services/detailed_statistics.py`

**Функция**: `get_user_detailed_statistics()`

**Ключ кеша**: `user_stats_{user_id}`

**TTL**: 600 секунд (10 минут)

**Описание**: Кешируется детальная статистика пользователя, включая:
- Данные за последние 6 месяцев
- Топ категории расходов/доходов
- Информация о чеках
- Балансы по валютам
- Данные кредитных карт

**Инвалидация**: При создании/обновлении транзакций:

```python
from django.core.cache import cache

cache.delete(f'user_stats_{user.id}')
```

### 3. Список счетов пользователя

**Модуль**: `hasta_la_vista_money/finance_account/services.py`

**Функция**: `get_accounts_for_user_or_group()`

**Ключ кеша**: `user_accounts_{user_id}_{group_id}`

**TTL**: 300 секунд (5 минут)

**Описание**: Кешируется список финансовых счетов пользователя или группы.

**Инвалидация**: При создании/обновлении/удалении счета:

```python
from django.core.cache import cache

cache.delete(f'user_accounts_{user.id}_all')
cache.delete(f'user_accounts_{user.id}_my')
```

### 4. Сессии пользователей

В продакшене сессии Django хранятся в Redis:

```python
if not DEBUG:
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
```

Преимущества:
- Быстрый доступ к данным сессии
- Автоматическая очистка истекших сессий
- Масштабируемость при использовании нескольких серверов

### 5. Django Axes (защита от брутфорса)

Axes использует Redis для отслеживания неудачных попыток входа:

```python
if not DEBUG:
    AXES_CACHE = 'default'
```

### 6. Проверка наличия суперпользователя

**Модуль**: `hasta_la_vista_money/users/middleware.py`

**Ключ кеша**: `has_superuser`

**TTL**: 300 секунд (5 минут)

**Описание**: Кешируется проверка наличия хотя бы одного суперпользователя в системе.

## API Rate Limiting (Throttling)

Throttling для API использует Redis в продакшене через модуль `hasta_la_vista_money/api/throttling_redis.py`:

- `RedisAnonRateThrottle` - ограничение для анонимных пользователей
- `RedisUserRateThrottle` - ограничение для авторизованных пользователей
- `RedisLoginRateThrottle` - ограничение попыток входа

**Конфигурация** в `config/django/base.py`:

```python
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'login': '5/min',
    },
}
```

## Управление кешем

### Очистка всего кеша

```python
from django.core.cache import cache
cache.clear()
```

### Очистка конкретного ключа

```python
cache.delete('user_stats_123')
```

### Массовая инвалидация

```python
keys_to_delete = [
    f'user_stats_{user_id}',
    f'user_accounts_{user_id}_all',
    f'category_tree_expense_{user_id}_3',
]
cache.delete_many(keys_to_delete)
```

### Проверка наличия ключа

```python
if cache.get('user_stats_123') is None:
    # Кеш отсутствует, нужно вычислить данные
    pass
```

## Мониторинг Redis

### Подключение к Redis в Docker

```bash
# Локальная разработка
docker exec -it hlvm-dev-redis-1 redis-cli

# Продакшен
docker exec -it hlvm-prod-redis-1 redis-cli
```

### Полезные команды Redis

```redis
# Проверка работоспособности
PING

# Просмотр всех ключей (осторожно в продакшене!)
KEYS *

# Просмотр ключей по паттерну
KEYS hlvm:user_stats_*

# Информация о ключе
TTL hlvm:user_stats_123
TYPE hlvm:user_stats_123

# Получение значения
GET hlvm:user_stats_123

# Удаление ключа
DEL hlvm:user_stats_123

# Статистика Redis
INFO stats
INFO memory

# Количество ключей в текущей БД
DBSIZE
```

## Производительность

### Оптимизация connection pool

В конфигурации Redis настроен connection pool:

```python
'CONNECTION_POOL_KWARGS': {'max_connections': 50}
```

Это позволяет эффективно использовать соединения с Redis при высокой нагрузке.

### Таймауты

Настроены таймауты для предотвращения зависания при проблемах с Redis:

```python
'SOCKET_CONNECT_TIMEOUT': 5,  # 5 секунд на подключение
'SOCKET_TIMEOUT': 5,          # 5 секунд на операцию
```

### Префикс ключей

Все ключи кеша имеют префикс `hlvm:` для изоляции от других приложений, использующих тот же Redis:

```python
'KEY_PREFIX': 'hlvm'
```

## Рекомендации

1. **Не кешируйте слишком долго**: Устанавливайте разумные TTL в зависимости от частоты изменения данных
2. **Явная инвалидация**: При изменении данных явно инвалидируйте связанные ключи кеша
3. **Мониторинг памяти**: Следите за использованием памяти Redis в продакшене
4. **Graceful degradation**: Приложение должно работать даже при недоступности Redis
5. **Тестирование**: Тестируйте работу с обоими бэкендами (LocMemCache и Redis)

## Устранение неполадок

### Redis не запускается

```bash
# Проверка логов
docker logs hlvm-prod-redis-1

# Проверка healthcheck
docker inspect hlvm-prod-redis-1 | grep -A 10 Health
```

### Подключение к Redis не работает

1. Проверьте переменную окружения `REDIS_LOCATION`
2. Убедитесь, что сервис Redis запущен
3. Проверьте сетевые настройки в docker-compose
4. Проверьте логи Django на ошибки подключения

### Кеш не инвалидируется

1. Убедитесь, что используете правильный ключ кеша
2. Проверьте, что инвалидация вызывается после изменения данных
3. Используйте `cache.clear()` для полной очистки в тестовых целях

## Тестирование

Для тестирования Redis кеша используйте:

```bash
make test
```

Тесты находятся в `config/django/tests/test_redis_cache.py` и проверяют:
- Конфигурацию кеша для разных окружений
- Базовые операции (set, get, delete)
- TTL и expiration
- Форматирование ключей кеша
- Работу с сложными типами данных

