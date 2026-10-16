# Техническая документация Django-приложения `users`

## Общее назначение приложения

Приложение `users` является основным компонентом системы управления пользователями в проекте "Hasta La Vista Money" - self-hosted финансового приложения. Оно обеспечивает:

- Регистрацию и аутентификацию пользователей
- Управление профилями пользователей  
- Систему групп и разрешений
- JWT-токены для API аутентификации
- Управление темами интерфейса
- Статистику и экспорт данных пользователей
- Интерактивный дашборд с настраиваемыми виджетами
- Уведомления

## Модели

### User (кастомная модель пользователя)

Расширяет стандартную Django модель `AbstractUser`:

```python
class User(AbstractUser):
    theme: CharField[Any, Any] = CharField(max_length=10, default='dark')
    
    def __str__(self) -> str:
        return self.username
```

**Поля:**

- Все стандартные поля `AbstractUser` (username, email, password, first_name, last_name, etc.)  
- `theme` - CharField(max_length=10, default='dark') - тема интерфейса пользователя

**Методы:**
- `__str__()` - возвращает username пользователя

### TokenAdmin

```python
class TokenAdmin(admin.ModelAdmin):
    search_fields = ('key', 'user__username')
```

Административный класс для управления токенами в Django Admin с поиском по ключу токена и имени пользователя.

## Аутентификация и авторизация

### Система аутентификации

Приложение использует комбинированную систему аутентификации:

1. **Django сессии** - для веб-интерфейса
2. **JWT токены** - для API (через `rest_framework_simplejwt`)

### Реализация аутентификации

**Сервис аутентификации** (`services/auth.py`):
```python
def login_user(request, form, success_message):
    user = authenticate(
        request,
        username=username,
        password=password,
        backend='django.contrib.auth.backends.ModelBackend',
    )
    if user is not None:
        login(request, user)
        tokens = RefreshToken.for_user(user)
        jwt_access_token = str(tokens.access_token)
        jwt_refresh_token = str(tokens)
        # Возвращает JWT токены для API использования
```

### Middleware

**`CheckAdminMiddleware`** - проверяет наличие суперпользователя в системе и перенаправляет на регистрацию, если его нет:

```python
def __call__(self, request):
    if not User.objects.filter(is_superuser=True).exists():
        if request.path != reverse_lazy('users:registration'):
            return redirect('users:registration')
    return self.get_response(request)
```

### Разрешения

Используется стандартная система групп Django:
- Управление группами через формы `GroupCreateForm`, `GroupDeleteForm`
- Вступление в группу только по приглашению; удаление участника — через `DeleteUserFromGroupForm` (владелец исключает, участник может выйти сам)

## Формы и валидация

### Основные формы

1. **`UserLoginForm`** - форма входа
   - Поддерживает вход по username или email
   - Поля: `username` (CharField), `password` (CharField)
   - Bootstrap классы для стилизации

2. **`RegisterUserForm`** - форма регистрации
   - Наследует от `UserCreationForm`
   - Поля: `username`, `email`, `password1`, `password2`
   - Кастомная валидация username через `validate_username_unique`

3. **`UpdateUserForm`** - форма обновления профиля
   - Поля: `username`, `email`, `first_name`, `last_name`
   - Bootstrap стилизация

### Формы управления группами

4. **`GroupCreateForm`** - создание группы
5. **`GroupDeleteForm`** - удаление группы  
6. **`DeleteUserFromGroupForm`** - удаление пользователя из группы

### Валидаторы

**`validate_username_unique`** (`validators.py`):
```python
def validate_username_unique(value: str) -> None:
    # Валидатор уникальности username (в настоящее время заглушка)
    pass
```

## URL-маршруты

### Основные маршруты (`urls.py`)

```python
urlpatterns = [
    path('registration/', CreateUser.as_view(), name='registration'),
    path('profile/<int:pk>/', ListUsers.as_view(), name='profile'),
    path('profile/password/', SetPasswordUserView.as_view(), name='password'),
    path('login/', LoginUser.as_view(), name='login'),
    path('update-user/<int:pk>/', UpdateUserView.as_view(), name='update_user'),
    path('list/users/', ListUsers.as_view(), name='list_users'),
    path('statistics/', UserStatisticsView.as_view(), name='statistics'),
    path('export-data/', ExportUserDataView.as_view(), name='export_data'),
    path('set-theme/', SwitchThemeView.as_view(), name='set_theme'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/data/', DashboardDataView.as_view(), name='dashboard_data'),
    path('dashboard/widget/', DashboardWidgetConfigView.as_view(), name='dashboard_widget'),
    path('dashboard/drilldown/', DashboardDrillDownView.as_view(), name='dashboard_drilldown'),
    path('dashboard/comparison/', DashboardComparisonView.as_view(), name='dashboard_comparison'),
    path('groups/', include('hasta_la_vista_money.users.groups_urls')),
    path('ajax/', include('hasta_la_vista_money.users.ajax_urls')),
]
```

### AJAX маршруты (`ajax_urls.py`)

```python
urlpatterns = [
    path('groups-for-user/', groups_for_user_ajax, name='groups_for_user'),
    path('groups-not-for-user/', groups_not_for_user_ajax, name='groups_not_for_user'),
]
```

### Маршруты групп (`groups_urls.py`)

```python
urlpatterns = [
    path('create/', GroupCreateView.as_view(), name='create'),
    path('delete/', GroupDeleteView.as_view(), name='delete'),
    path('delete-user/', DeleteUserFromGroupView.as_view(), name='delete_user'),
]
```

## Представления (Views)

### Основные представления

1. **`CreateUser`** - регистрация пользователей
2. **`LoginUser`** - аутентификация пользователей с JWT токенами
3. **`ListUsers`** - профиль пользователя с статистикой
4. **`UpdateUserView`** - обновление профиля
5. **`SetPasswordUserView`** - смена пароля
6. **`UserStatisticsView`** - детальная статистика пользователя
7. **`ExportUserDataView`** - экспорт данных пользователя
8. **`SwitchThemeView`** - переключение темы интерфейса
9. **`DashboardView`** - главная страница интерактивного дашборда
10. **`DashboardDataView`** - API endpoint для получения данных дашборда
11. **`DashboardWidgetConfigView`** - управление виджетами (создание, обновление, удаление)
12. **`DashboardDrillDownView`** - API для drill-down данных по категориям
13. **`DashboardComparisonView`** - API для сравнения периодов

### AJAX представления

- `groups_for_user_ajax` - получение групп пользователя
- `groups_not_for_user_ajax` - получение доступных групп для пользователя

## Сервисы (Services Layer)

Приложение использует Service Layer архитектуру для бизнес-логики:

### `services/auth.py`
- `login_user()` - аутентификация с генерацией JWT токенов
- `set_auth_cookies_in_response()` - установка JWT cookies

### `services/groups.py`
- `get_user_groups()` - получение групп пользователя
- `create_group()` - создание группы
- `delete_group()` - удаление группы
- `remove_user_from_group()` - удаление пользователя из группы

### `services/statistics.py`
- `get_user_statistics()` - базовая статистика пользователя (баланс, расходы, доходы)

### `services/dashboard_analytics.py`
- `calculate_linear_trend()` - расчёт линейной регрессии и прогноза через NumPy
- `get_period_comparison()` - сравнение текущего и предыдущего периода (месяц/квартал/год)
- `get_drill_down_data()` - детализация данных по категориям для drill-down графиков

### Другие сервисы
- `detailed_statistics.py` - детальная статистика (304 строки)
- `export.py` - экспорт данных пользователя
- `notifications.py` - система уведомлений
- `password.py` - управление паролями
- `profile.py` - управление профилем
- `registration.py` - регистрация пользователей
- `theme.py` - управление темами

## Настройки

### Влияющие параметры settings.py

1. **`AUTH_USER_MODEL`** - установлена в `config/django/base.py`:
   ```python
   AUTH_USER_MODEL = 'users.User'
   ```

2. **JWT токены** - настройки `SIMPLE_JWT` в `config/django/base.py`:
   ```python
   SIMPLE_JWT = {
       'ACCESS_TOKEN_LIFETIME': timedelta(
           minutes=int(os.environ.get('ACCESS_TOKEN_LIFETIME', '60')),
       ),
       'REFRESH_TOKEN_LIFETIME': timedelta(
           days=int(os.environ.get('REFRESH_TOKEN_LIFETIME', '7')),
       ),
       'AUTH_COOKIE': 'access_token',
       'AUTH_COOKIE_REFRESH': 'refresh_token',
       'AUTH_COOKIE_DOMAIN': None,
       'AUTH_COOKIE_SECURE': os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
       'AUTH_COOKIE_HTTP_ONLY': True,
       'AUTH_COOKIE_PATH': '/',
       'AUTH_COOKIE_SAMESITE': 'Lax',
       'AUTH_COOKIE_MAX_AGE': int(os.environ.get('ACCESS_TOKEN_LIFETIME', '60')) * 60,
       'AUTH_COOKIE_REFRESH_MAX_AGE': int(os.environ.get('REFRESH_TOKEN_LIFETIME', '7')) * 24 * 60 * 60,
   }
   ```

3. **REST Framework** - настройки аутентификации:
   ```python
   REST_FRAMEWORK = {
       'DEFAULT_AUTHENTICATION_CLASSES': (
           'hasta_la_vista_money.authentication.authentication.CookieJWTAuthentication',
           'rest_framework_simplejwt.authentication.JWTAuthentication',
       ),
   }
   ```

4. **Authentication backends**:
   ```python
   AUTHENTICATION_BACKENDS = (
       'axes.backends.AxesStandaloneBackend',
       'django.contrib.auth.backends.ModelBackend',
   )
   ```

5. **Middleware** - `CheckAdminMiddleware` должен быть добавлен в `MIDDLEWARE`

## Интеграции

### Зависимости от других приложений

1. **`authentication`** - приложение для работы с JWT cookies
2. **`expense`** - модель `Expense` для статистики
3. **`income`** - модель `Income` для статистики  
4. **`finance_account`** - модель `Account` для статистики
5. **`receipts`** - модель `Receipt` для статистики

### Внешние зависимости

- `rest_framework_simplejwt` - JWT токены
- `django_stubs_ext` - типизация для Django
- Стандартные Django компоненты (auth, admin, messages, etc.)

## Шаблоны

Приложение включает следующие шаблоны:

- `login.html` - страница входа
- `registration.html` - страница регистрации
- `profile.html` - профиль пользователя (23KB)
- `statistics.html` - статистика пользователя (35KB)
- `dashboard.html` - интерактивный дашборд с настраиваемыми виджетами
- `notifications.html` - уведомления
- `set_password.html` - смена пароля
- Шаблоны для управления группами

## Тестирование

### Структура тестов

Приложение имеет комплексное покрытие тестами:

- `test_auth.py` - тесты аутентификации
- `test_groups.py` - тесты управления группами
- `test_user.py` - тесты модели пользователя
- `test_statistics.py` - тесты статистики
- `test_notifications.py` - тесты уведомлений
- `test_dashboard_analytics.py` - тесты аналитических сервисов дашборда
- `test_dashboard_views.py` - тесты views дашборда
- `test_urls.py` - тесты URL маршрутов (162 строки)
- И другие тестовые модули для каждого сервиса

## Миграции

Ключевые миграции:

- `0001_initial.py` - создание кастомной модели User
- `0002_user_theme.py` - добавление поля theme
- `0003_alter_user_theme.py` - изменение поля theme
- `0004_dashboardwidget.py` - создание модели DashboardWidget для настраиваемых виджетов

## Функционал личного кабинета пользователя

### Обзор интерфейса профиля

Личный кабинет пользователя (`/profile/<user_id>/`) представляет собой полнофункциональную панель управления с несколькими разделами, организованными через вкладочный интерфейс.

### Основная информация пользователя

В шапке профиля отображается:

- **Аватар** - цветная иконка с первой буквой имени пользователя
- **Полное имя** - отображается `get_full_name()` или username, если имя не указано
- **Email** - адрес электронной почты (или "Email не указан")
- **Дата регистрации** - когда пользователь зарегистрировался в системе

### Финансовая статистика (дашборд)

Пользователь видит 4 основные метрики в виде карточек:

1. **Общий баланс** 💰
    - Сумма всех средств на счетах пользователя  

2. **Доходы (месяц)** 📈
    - Доходы за текущий месяц  

3. **Расходы (месяц)** 📉
    - Расходы за текущий месяц  

4. **Сбережения** 🐷
    - Разница между доходами и расходами за месяц
    - Цвет карточки меняется в зависимости от значения (синий для положительных, желтый для отрицательных)  

### Вкладки интерфейса

#### 1. Персональная информация

- **Редактирование профиля**: форма для изменения username, email, имени и фамилии
- **Мои группы**: список групп, в которых состоит пользователь
- **Кнопка сохранения** изменений профиля

#### 2. Статистика

**Общая информация:**

- Количество финансовых счетов
- Количество чеков
- Сравнение с прошлым месяцем (индикатор роста/падения)

**Топ категорий расходов:**

- Список категорий с наибольшими тратами за текущий месяц
- Сумма трат по каждой категории

**Кнопка "Детальная статистика"** - ведет на отдельную страницу с расширенной аналитикой

#### 3. Последние операции

**Два блока:**

- **Последние расходы** (5 записей):
  - Название категории
  - Сумма расхода
  - Счет, с которого списано
  - Дата операции

- **Последние доходы** (5 записей):
  - Название категории
  - Сумма дохода
  - Счет, на который поступило
  - Дата операции

#### 4. Настройки

**Безопасность:**

- **Изменить пароль** - переход к форме смены пароля
- **Управление счетами** - переход к списку финансовых счетов
- **Отчеты и аналитика** - переход к модулю отчетов

**Управление группами:**

- Создать группу
- Удалить группу
- Добавить пользователя в группу
- Удалить пользователя из группы

**Быстрые действия:**

- **Добавить расход** - переход к модулю расходов
- **Добавить доход** - переход к модулю доходов
- **Добавить чек** - переход к модулю чеков
- **Экспорт данных** - выгрузка данных пользователя

**Управление темой:**

- **Переключатель темы** - смена между светлой и темной темой интерфейса

### Детальная статистика

При переходе по кнопке "Детальная статистика" (`/statistics/`) пользователь попадает на страницу с расширенной аналитикой:

- **Статистика по счетам**: общее количество и баланс по валютам
- **Количество чеков**
- **Подробные графики и диаграммы** (35KB HTML-кода указывает на богатый функционал)
- **Сравнительный анализ по периодам**

### Экспорт данных

Функция экспорта (`/export-data/`) позволяет пользователю:

- Выгрузить все свои финансовые данные
- Получить отчеты в различных форматах
- Создать резервную копию информации

### Адаптивный дизайн

Интерфейс полностью адаптивен:

- Использует Bootstrap 5 для responsive-дизайна
- Карточки перестраиваются на мобильных устройствах
- Вкладочный интерфейс оптимизирован для touch-устройств

### Интерактивность

- **AJAX-формы** для обновления данных без перезагрузки страницы
- **Динамическое переключение тем**
- **Иконки Bootstrap Icons** для визуального улучшения
- **Кастомные стили** с градиентами для аватара и современным дизайном карточек

## Интерактивный дашборд

### Обзор

Дашборд (`/dashboard/`) предоставляет пользователю настраиваемый интерфейс для визуализации финансовых данных с помощью интерактивных виджетов. Реализован с использованием Apache ECharts для графиков и Sortable.js для drag-and-drop перестановки виджетов.

### Модель DashboardWidget

```python
class DashboardWidget(Model):
    user = ForeignKey(User, on_delete=CASCADE, related_name='dashboard_widgets')
    widget_type = CharField(max_length=50)
    position = PositiveIntegerField(default=0)
    width = PositiveIntegerField(default=6)
    height = PositiveIntegerField(default=300)
    config = JSONField(default=dict)
    is_visible = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

**Поля:**
- `user` - владелец виджета
- `widget_type` - тип виджета (balance, expenses_chart, income_chart, comparison, trend, top_categories, recent_transactions)
- `position` - позиция виджета в сетке (для сортировки)
- `width` - ширина виджета в колонках (1-12)
- `height` - высота виджета в пикселях
- `config` - дополнительные настройки виджета (JSON)
- `is_visible` - видимость виджета

### Доступные виджеты

1. **Баланс счетов** (`balance`)
   - График изменения баланса по месяцам

2. **График расходов** (`expenses_chart`)
   - Динамика расходов с возможностью drill-down по категориям

3. **График доходов** (`income_chart`)
   - Динамика доходов с возможностью drill-down по категориям

4. **Сравнение периодов** (`comparison`)
   - Сравнение текущего и предыдущего периода (месяц/квартал/год)

5. **Динамика и прогнозы** (`trend`)
   - Линейная регрессия расходов с прогнозом на 3 месяца вперёд

6. **Топ категорий** (`top_categories`)
   - Круговая диаграмма топ-10 категорий расходов с drill-down

7. **Последние операции** (`recent_transactions`)
   - Список последних 5 операций (расходы и доходы) с информацией о категории, счёте и дате

### API Endpoints

#### GET `/users/dashboard/data/`
Получение всех данных для дашборда в JSON формате.

**Параметры:**
- `period` (query) - период для сравнения: `month`, `quarter`, `year` (по умолчанию: `month`)

**Ответ:**
```json
{
  "widgets": [...],
  "analytics": {
    "stats": {...},
    "trends": {...}
  },
  "comparison": {...},
  "recent_transactions": [...]
}
```

#### POST `/users/dashboard/widget/`
Управление виджетами (создание, обновление, удаление).

**Тело запроса:**
```json
{
  "widget_id": 1,  // опционально, для обновления/удаления
  "widget_type": "balance",
  "position": 0,
  "width": 6,
  "height": 300,
  "config": {},
  "action": "delete"  // опционально, для удаления
}
```

#### GET `/users/dashboard/drilldown/`
Получение drill-down данных по категории.

**Параметры:**
- `category_id` - ID категории
- `type` - тип: `expense` или `income`

#### GET `/users/dashboard/comparison/`
Получение данных сравнения периодов.

**Параметры:**
- `period` - период: `month`, `quarter`, `year`

### Сервисы аналитики

#### `calculate_linear_trend(dates, values)`
Рассчитывает линейную регрессию и прогноз на основе исторических данных.

**Параметры:**
- `dates` - список дат (list[date])
- `values` - список значений для каждой даты (list[Decimal])

**Возвращает:**
```python
{
    'slope': float,  # коэффициент наклона
    'intercept': float,  # точка пересечения
    'r_squared': float,  # коэффициент детерминации (R²)
    'trend_line': list[dict],  # точки линии динамики
    'forecast': list[dict]  # прогноз на 3 месяца вперёд
}
```

#### `get_period_comparison(user, period)`
Сравнение текущего и предыдущего периода.

**Параметры:**
- `user` - пользователь (User)
- `period` - период: `'month'`, `'quarter'`, `'year'`

**Возвращает:**
```python
{
    'current': {
        'expenses': Decimal,
        'income': Decimal
    },
    'previous': {
        'expenses': Decimal,
        'income': Decimal
    }
}
```

#### `get_drill_down_data(user, category_id, type)`
Получение детализации по категории для drill-down графиков.

**Параметры:**
- `user` - пользователь (User)
- `category_id` - ID категории
- `type` - тип: `'expense'` или `'income'`

### Frontend компоненты

#### JavaScript модули

- **`dashboard.js`** - основной класс `DashboardManager` для управления дашбордом
- **`chart-configs.js`** - конфигурации графиков для ECharts
- **`chart-utils.js`** - утилиты для работы с графиками

#### Функциональность

- **Drag & Drop** - перестановка виджетов с сохранением позиций
- **Редактирование виджетов** - изменение размера и настроек
- **Drill-down** - детализация данных по клику на элементы графиков
- **Переключение периодов** - динамическое обновление данных при смене периода
- **Адаптивный дизайн** - автоматическая подстройка под размер экрана

### Использование

#### Добавление нового типа виджета

1. Добавить новый `case` в `renderWidgetChart()` в `dashboard.js`
2. Реализовать метод рендеринга (например, `renderMyWidget()`)
3. Добавить конфигурацию в `chart-configs.js` (если нужен график)
4. Обновить список доступных виджетов в `DashboardView.get_context_data()`

#### Кастомизация стилей

Стили дашборда находятся в `static/scss/_dashboard.scss` и могут быть кастомизированы через переменные Bootstrap.

## Как использовать/расширять

### Расширение модели User

```python
# Добавление новых полей
class User(AbstractUser):
    theme = CharField(max_length=10, default='dark')
    # Добавить новые поля здесь
    avatar = ImageField(upload_to='avatars/', blank=True, null=True)
```

### Создание новых сервисов

```python
# users/services/my_service.py
def my_custom_service(user: User) -> Any:
    # Бизнес-логика
    return result
```

### Добавление новых форм

```python
# Наследование от базовых форм
class MyCustomForm(ModelForm):
    class Meta:
        model = User
        fields = ['field1', 'field2']
```

### Расширение API

1. Добавить новые views в `views.py`
2. Добавить маршруты в соответствующий urls.py
3. Создать сервисы для бизнес-логики
4. Добавить тесты

### Настройка JWT токенов

В settings.py можно настроить параметры JWT через `SIMPLE_JWT`:

```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    # другие настройки
}
```

### Кастомизация middleware

Можно расширить `CheckAdminMiddleware` или создать новый:

```python
class CustomMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Кастомная логика
        return self.get_response(request)
``` 