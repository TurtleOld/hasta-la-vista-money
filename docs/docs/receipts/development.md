# Руководство разработчика - Чеки

!!! abstract "Разработка"

    Руководство для разработчиков по работе с модулем чеков, включая архитектуру, модели данных, API и интеграции.

## Архитектура модуля

### Структура проекта

```
hasta_la_vista_money/receipts/
├── __init__.py
├── admin.py              # Административная панель
├── apps.py               # Конфигурация приложения
├── models.py             # Модели данных
├── views.py              # Представления
├── forms.py              # Формы
├── serializers.py        # API сериализаторы
├── urls.py               # URL маршруты
├── services.py           # Бизнес-логика и ИИ
├── apis.py               # API представления
├── tests.py              # Тесты
├── migrations/           # Миграции БД
├── templates/            # Шаблоны
└── json_parser/          # Парсеры JSON
```

### Основные компоненты

```python
# Модели данных
class Seller(models.Model):      # Продавец/магазин
class Product(models.Model):     # Товар в чеке
class Receipt(models.Model):     # Кассовый чек

# Представления
class ReceiptView(FilterView):           # Список чеков
class ReceiptCreateView(CreateView):     # Создание чека
class ReceiptDeleteView(DeleteView):     # Удаление чека
class UploadImageView(FormView):         # Загрузка изображений

# Сервисы
def analyze_image_with_ai():     # ИИ-обработка
def image_to_base64():           # Кодирование изображений
```

## Модели данных

### Seller (Продавец)

```python
class Seller(models.Model):
    """Модель продавца/магазина."""
    
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name_seller = models.CharField(max_length=255)
    retail_place_address = models.CharField(max_length=1000, blank=True)
    retail_place = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self) -> str:
        return self.name_seller
```

**Особенности:**
- Связь с пользователем для изоляции данных
- Опциональные поля адреса и места расчетов
- Автоматическое создание временной метки

### Product (Товар)

```python
class Product(models.Model):
    """Модель товара в чеке."""
    
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=1000)
    category = models.CharField(max_length=250, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    nds_type = models.IntegerField(null=True, blank=True)
    nds_sum = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.product_name
```

**Особенности:**
- Поддержка НДС с разными ставками
- Автоматический расчет суммы (price × quantity)
- Категоризация товаров

### Receipt (Чек)

```python
class Receipt(models.Model):
    """Модель кассового чека."""
    
    receipt_date = models.DateTimeField()
    number_receipt = models.IntegerField(null=True)
    total_sum = models.DecimalField(max_digits=10, decimal_places=2)
    operation_type = models.IntegerField(choices=OPERATION_TYPES)
    manual = models.BooleanField(null=True)  # True для ручного ввода
    nds10 = models.DecimalField(max_digits=60, decimal_places=2, null=True)
    nds20 = models.DecimalField(max_digits=60, decimal_places=2, null=True)
    
    # Связи
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    product = models.ManyToManyField(Product)
    
    class Meta:
        ordering = ['-receipt_date']
        indexes = [
            models.Index(fields=['-receipt_date']),
            models.Index(fields=['number_receipt']),
            models.Index(fields=['operation_type']),
        ]
```

**Особенности:**
- Индексы для оптимизации запросов
- Сортировка по дате (новые сверху)
- Разделение на ручные и автоматические чеки

## Бизнес-логика

### Создание чека

```python
def create_receipt(request, receipt_form, product_formset, seller):
    """Создание чека с проверкой баланса."""
    
    receipt = receipt_form.save(commit=False)
    total_sum = receipt.total_sum
    account = receipt.account
    
    # Проверка баланса
    account_balance = get_object_or_404(Account, id=account.id)
    if account_balance.user == request.user:
        account_balance.balance -= total_sum
        account_balance.save()
        
        # Создание чека
        receipt.user = request.user
        receipt.seller = seller
        receipt.manual = True
        receipt.save()
        
        # Добавление товаров
        for product_form in product_formset:
            product = product_form.save(commit=False)
            product.user = request.user
            product.save()
            receipt.product.add(product)
            
        return receipt
```

### ИИ-обработка изображений

```python
def analyze_image_with_ai(image_base64: UploadedFile):
    """Обработка изображения чека с помощью ИИ."""
    
    client = OpenAI(
        base_url=os.environ.get('API_BASE_URL'),
        api_key=os.environ.get('API_KEY')
    )
    
    response = client.chat.completions.create(
        model=os.environ.get('API_MODEL', 'openai/gpt-4o'),
        temperature=0.6,
        messages=[
            {
                'role': 'system',
                'content': 'Системный промпт для извлечения данных'
            },
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'Инструкции по обработке'},
                    {'type': 'image_url', 'image_url': {'url': image_to_base64(image_base64)}}
                ]
            }
        ]
    )
    return response.choices[0].message.content
```

## API разработка

### Сериализаторы

```python
class ProductSerializer(serializers.ModelSerializer):
    """Сериализатор для товаров."""
    
    class Meta:
        model = Product
        fields = [
            'id', 'product_name', 'category', 'price',
            'quantity', 'amount', 'nds_type', 'nds_sum'
        ]
        read_only_fields = ['id', 'created_at']

class ReceiptSerializer(serializers.ModelSerializer):
    """Сериализатор для чеков."""
    
    seller = SellerSerializer(read_only=True)
    account = AccountSerializer(read_only=True)
    products = ProductSerializer(many=True, read_only=True)
    
    class Meta:
        model = Receipt
        fields = [
            'id', 'receipt_date', 'number_receipt', 'total_sum',
            'operation_type', 'manual', 'nds10', 'nds20',
            'seller', 'account', 'products', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
```

### API представления

```python
class ReceiptViewSet(viewsets.ModelViewSet):
    """ViewSet для чеков."""
    
    serializer_class = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['seller', 'account', 'operation_type']
    search_fields = ['seller__name_seller', 'products__product_name']
    ordering_fields = ['receipt_date', 'total_sum', 'created_at']
    ordering = ['-receipt_date']
    
    def get_queryset(self):
        return Receipt.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
```

## Формы и валидация

### Форма чека

```python
class ReceiptForm(forms.ModelForm):
    """Форма для создания/редактирования чека."""
    
    class Meta:
        model = Receipt
        fields = [
            'receipt_date', 'number_receipt', 'total_sum',
            'operation_type', 'seller', 'account', 'nds10', 'nds20'
        ]
        widgets = {
            'receipt_date': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}
            )
        }
    
    def clean(self):
        cleaned_data = super().clean()
        total_sum = cleaned_data.get('total_sum')
        account = cleaned_data.get('account')
        
        # Проверка баланса
        if total_sum and account:
            if total_sum > account.balance:
                raise ValidationError("Недостаточно средств на счете")
        
        return cleaned_data
```

### FormSet для товаров

```python
ProductFormSet = forms.inlineformset_factory(
    Receipt,
    Product,
    fields=['product_name', 'category', 'price', 'quantity', 'amount'],
    extra=1,
    can_delete=True
)
```

## Тестирование

### Модельные тесты

```python
class ReceiptModelTest(TestCase):
    """Тесты для модели Receipt."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=1000.00
        )
        self.seller = Seller.objects.create(
            user=self.user,
            name_seller='Test Seller'
        )
    
    def test_receipt_creation(self):
        """Тест создания чека."""
        receipt = Receipt.objects.create(
            receipt_date=timezone.now(),
            total_sum=100.00,
            operation_type=1,
            seller=self.seller,
            user=self.user,
            account=self.account
        )
        
        self.assertEqual(receipt.total_sum, 100.00)
        self.assertEqual(receipt.operation_type, 1)
        self.assertTrue(receipt.manual)
```

### API тесты

```python
class ReceiptAPITest(APITestCase):
    """Тесты для API чеков."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.force_authenticate(user=self.user)
    
    def test_create_receipt(self):
        """Тест создания чека через API."""
        data = {
            'receipt_date': '2023-12-20T15:30:00Z',
            'total_sum': '100.00',
            'operation_type': 1,
            'seller': 1,
            'account': 1
        }
        
        response = self.client.post('/api/receipts/', data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Receipt.objects.count(), 1)
```

### Интеграционные тесты

```python
class ReceiptIntegrationTest(TestCase):
    """Интеграционные тесты для чеков."""
    
    def test_receipt_with_products(self):
        """Тест создания чека с товарами."""
        # Создание чека
        receipt = Receipt.objects.create(...)
        
        # Добавление товаров
        product1 = Product.objects.create(
            product_name='Молоко',
            price=85.00,
            quantity=2.00,
            amount=170.00
        )
        receipt.product.add(product1)
        
        # Проверка
        self.assertEqual(receipt.product.count(), 1)
        self.assertEqual(receipt.total_sum, 170.00)
```

## Оптимизация производительности

### Оптимизация запросов

```python
# Использование select_related для уменьшения запросов
receipts = Receipt.objects.select_related(
    'seller', 'account', 'user'
).filter(user=request.user)

# Использование prefetch_related для ManyToMany
receipts = Receipt.objects.prefetch_related(
    'product'
).filter(user=request.user)

# Аннотации для агрегации
stats = Receipt.objects.filter(user=user).aggregate(
    total_sum=Sum('total_sum'),
    total_count=Count('id'),
    avg_sum=Avg('total_sum')
)
```

### Кэширование

```python
from django.core.cache import cache

def get_receipt_statistics(user):
    """Получение статистики чеков с кэшированием."""
    cache_key = f'receipt_stats_{user.id}'
    stats = cache.get(cache_key)
    
    if stats is None:
        stats = Receipt.objects.filter(user=user).aggregate(
            total_sum=Sum('total_sum'),
            total_count=Count('id')
        )
        cache.set(cache_key, stats, 300)  # 5 минут
    
    return stats
```

### Индексы базы данных

```python
class Receipt(models.Model):
    # ... поля модели ...
    
    class Meta:
        indexes = [
            models.Index(fields=['-receipt_date']),
            models.Index(fields=['user', '-receipt_date']),
            models.Index(fields=['seller', 'receipt_date']),
            models.Index(fields=['operation_type', 'receipt_date']),
        ]
```

## Безопасность

### Валидация данных

```python
def validate_receipt_data(data):
    """Валидация данных чека."""
    errors = {}
    
    # Проверка суммы
    if data.get('total_sum', 0) <= 0:
        errors['total_sum'] = 'Сумма должна быть больше нуля'
    
    # Проверка даты
    receipt_date = data.get('receipt_date')
    if receipt_date and receipt_date > timezone.now():
        errors['receipt_date'] = 'Дата не может быть в будущем'
    
    # Проверка номера чека
    number_receipt = data.get('number_receipt')
    if number_receipt:
        existing = Receipt.objects.filter(
            user=data['user'],
            number_receipt=number_receipt
        ).exists()
        if existing:
            errors['number_receipt'] = 'Чек с таким номером уже существует'
    
    return errors
```

### Права доступа

```python
class ReceiptPermission(BasePermission):
    """Права доступа для чеков."""
    
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user
```

## Логирование

### Настройка логирования

```python
import structlog

logger = structlog.get_logger(__name__)

def log_receipt_operation(operation, receipt, user):
    """Логирование операций с чеками."""
    logger.info(
        "Receipt operation",
        operation=operation,
        receipt_id=receipt.id,
        user_id=user.id,
        total_sum=str(receipt.total_sum),
        seller=receipt.seller.name_seller
    )
```

### Обработка ошибок

```python
def handle_receipt_error(error, context):
    """Обработка ошибок при работе с чеками."""
    logger.error(
        "Receipt error",
        error=str(error),
        context=context,
        exc_info=True
    )
    
    # Уведомление администратора
    if settings.DEBUG:
        raise error
    else:
        # Отправка уведомления
        send_error_notification(error, context)
```

## Развертывание

### Переменные окружения

```bash
# ИИ-сервис
API_BASE_URL=https://models.github.ai/inference
API_KEY=your_api_key_here
API_MODEL=openai/gpt-4o

# Настройки обработки
RECEIPT_MAX_FILE_SIZE=10485760  # 10 МБ
RECEIPT_ALLOWED_FORMATS=jpg,jpeg,png
RECEIPT_PROCESSING_TIMEOUT=30  # секунды
```

### Миграции

```bash
# Создание миграции
python manage.py makemigrations receipts

# Применение миграций
python manage.py migrate receipts

# Проверка миграций
python manage.py showmigrations receipts
```

## Расширение функциональности

### Добавление новых типов операций

```python
# Расширение OPERATION_TYPES
OPERATION_TYPES = (
    (1, _('Покупка')),
    (2, _('Возврат средств за покупку')),
    (3, _('Продажа/Выигрыш')),
    (4, _('Возврат выигрыша или продажи')),
    (5, _('Новый тип операции')),  # Добавить новый тип
)
```

### Интеграция с внешними сервисами

```python
def integrate_with_bank_api(receipt_data):
    """Интеграция с банковским API."""
    # Отправка данных в банк
    bank_response = send_to_bank_api(receipt_data)
    
    # Обработка ответа
    if bank_response.success:
        receipt_data['bank_transaction_id'] = bank_response.transaction_id
        return receipt_data
    else:
        raise BankIntegrationError(bank_response.error)
```

### Кастомные фильтры

```python
class ReceiptFilter(django_filters.FilterSet):
    """Кастомные фильтры для чеков."""
    
    date_range = django_filters.DateFromToRangeFilter(
        field_name='receipt_date',
        label='Период'
    )
    
    total_sum_range = django_filters.RangeFilter(
        field_name='total_sum',
        label='Диапазон сумм'
    )
    
    class Meta:
        model = Receipt
        fields = {
            'seller': ['exact'],
            'account': ['exact'],
            'operation_type': ['exact'],
        }
```
