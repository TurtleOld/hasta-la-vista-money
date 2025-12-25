# Руководство по стилю кода

Этот документ описывает стандарты и соглашения по написанию кода в проекте **Hasta La Vista, Money!**. Следование этим правилам обеспечивает единообразие кода и упрощает его поддержку.

## Содержание

1. [Общие принципы](#общие-принципы)
2. [Именование](#именование)
3. [Документация](#документация)
4. [Типизация](#типизация)
5. [Структура кода](#структура-кода)
6. [Обработка ошибок](#обработка-ошибок)
7. [Тестирование](#тестирование)
8. [Примеры](#примеры)

---

## Общие принципы

### PEP 8

Проект следует стандарту PEP 8 с некоторыми дополнениями:

- Максимальная длина строки: **80 символов**
- Использование одинарных кавычек (`'`) для строк
- 4 пробела для отступов (не табы)
- Использование `ruff` для линтинга и форматирования

### Читабельность превыше всего

Код должен быть понятен без комментариев. Если код требует комментария, возможно, его стоит упростить.

### DRY (Don't Repeat Yourself)

Избегайте дублирования кода. Выносите общую логику в:
- Базовые классы и миксины
- Утилитные функции
- Сервисы

---

## Именование

### Классы

**PascalCase** для всех классов:

```python
class ExpenseService:
    pass

class AccountRepository:
    pass

class CreditCalculationService:
    pass
```

### Функции и методы

**snake_case** для функций и методов:

```python
def create_expense(data: dict) -> Expense:
    pass

def get_account_balance(account: Account) -> Decimal:
    pass
```

### Переменные

**snake_case** для переменных:

```python
expense_amount = Decimal('100.00')
user_account = Account.objects.get(pk=1)
total_sum = calculate_total(expenses)
```

### Константы

**UPPER_SNAKE_CASE** для констант:

```python
PAGINATE_BY_DEFAULT = 10
MAX_FILE_SIZE_MB = 5
ACCOUNT_TYPE_CREDIT = 'Credit'
```

### Приватные методы и атрибуты

Используйте префикс `_` для приватных методов и атрибутов:

```python
class ExpenseService:
    def _validate_amount(self, amount: Decimal) -> None:
        pass
    
    def _calculate_tax(self, amount: Decimal) -> Decimal:
        pass
```

### Булевы методы и переменные

Используйте префиксы `is_`, `has_`, `should_`, `can_` для булевых значений:

```python
def is_authenticated(self) -> bool:
    pass

def has_permission(self, user: User) -> bool:
    pass

def should_apply_discount(self, amount: Decimal) -> bool:
    pass

can_delete = account.balance == ZERO
is_valid = form.is_valid()
```

### Методы действий

Используйте глаголы для методов, выполняющих действия:

```python
def create_expense(self, data: dict) -> Expense:
    pass

def update_account(self, account: Account, data: dict) -> Account:
    pass

def delete_receipt(self, receipt: Receipt) -> None:
    pass

def calculate_interest(self, principal: Decimal, rate: float) -> Decimal:
    pass
```

### Избегайте сокращений

Используйте полные, понятные имена:

```python
# ❌ Плохо
def calc_int(pr: Decimal, rt: float) -> Decimal:
    pass

# ✅ Хорошо
def calculate_interest(principal: Decimal, rate: float) -> Decimal:
    pass
```

---

## Документация

### Docstrings

Все публичные классы и методы должны иметь docstrings в формате **Google style**:

```python
class ExpenseService:
    """Service for managing expense operations.
    
    This service handles creation, updating, and deletion of expenses,
    as well as category management.
    """
    
    def create_expense(
        self,
        user: User,
        account: Account,
        amount: Decimal,
        category: ExpenseCategory,
        date: date,
        notes: str | None = None,
    ) -> Expense:
        """Create a new expense record.
        
        Args:
            user: User who owns the expense
            account: Account from which the expense is made
            amount: Expense amount (must be positive)
            category: Expense category
            date: Date of the expense
            notes: Optional notes for the expense
            
        Returns:
            Created Expense instance
            
        Raises:
            ValidationError: If amount is negative or account balance
                is insufficient
            ValueError: If account does not belong to user
                
        Example:
            >>> service = ExpenseService(...)
            >>> expense = service.create_expense(
            ...     user=user,
            ...     account=account,
            ...     amount=Decimal('100.00'),
            ...     category=category,
            ...     date=date.today(),
            ... )
        """
        pass
```

### Модули

Каждый модуль должен начинаться с docstring:

```python
"""Expense service module.

This module provides services for managing expenses, including
creation, updates, and category management.
"""

from decimal import Decimal
# ...
```

### Сложная логика

Добавляйте комментарии для объяснения сложной бизнес-логики:

```python
def calculate_raiffeisenbank_payment_schedule(
    self,
    account: Account,
    start_date: date,
) -> list[dict]:
    """Calculate payment schedule for Raiffeisenbank credit card.
    
    The calculation considers:
    - Grace period of 110 days
    - Statement date (2nd day of month)
    - Payment due date (20 days after statement)
    - Minimum payment (3% of debt)
    """
    # Calculate grace period end date
    grace_period_end = start_date + timedelta(days=110)
    
    # If payment is made within grace period, no interest is charged
    if payment_date <= grace_period_end:
        return calculate_without_interest(...)
    
    # Otherwise, calculate interest from statement date
    return calculate_with_interest(...)
```

---

## Типизация

### Type Hints

Все функции и методы должны иметь type hints:

```python
def calculate_total(
    expenses: QuerySet[Expense],
    start_date: date,
    end_date: date,
) -> Decimal:
    pass
```

### Использование `Any`

Избегайте использования `Any`. Используйте конкретные типы или `Protocol`:

```python
# ❌ Плохо
def process_data(data: Any) -> Any:
    pass

# ✅ Хорошо
def process_data(data: dict[str, str | int]) -> ProcessedData:
    pass

# ✅ Хорошо (с Protocol)
def process_data(data: ProcessableData) -> ProcessedData:
    pass
```

### Type Aliases

Используйте type aliases для сложных типов:

```python
from typing import TypeAlias

AccountBalance: TypeAlias = Decimal
TransactionAmount: TypeAlias = Decimal
```

### TypedDict

Используйте `TypedDict` для словарей с известной структурой:

```python
from typing import TypedDict

class AccountSummary(TypedDict):
    balance: Decimal
    debt: Decimal
    available_limit: Decimal
```

---

## Структура кода

### Длина методов

Методы не должны превышать **50 строк**. Если метод длиннее, разбейте его на более мелкие методы:

```python
# ❌ Плохо (метод слишком длинный)
def process_receipt(self, receipt_data: dict) -> Receipt:
    # 100+ строк кода
    pass

# ✅ Хорошо (разбито на методы)
def process_receipt(self, receipt_data: dict) -> Receipt:
    validated_data = self._validate_receipt_data(receipt_data)
    parsed_data = self._parse_receipt_data(validated_data)
    duplicate_check = self._check_duplicates(parsed_data)
    return self._create_receipt(parsed_data, duplicate_check)
```

### Уровни вложенности

Избегайте глубокой вложенности (более 3 уровней). Используйте ранние возвраты:

```python
# ❌ Плохо
def process_payment(account: Account, amount: Decimal) -> bool:
    if account:
        if account.balance >= amount:
            if account.is_active:
                # обработка
                return True
            else:
                return False
        else:
            return False
    else:
        return False

# ✅ Хорошо
def process_payment(account: Account, amount: Decimal) -> bool:
    if not account:
        return False
    
    if not account.is_active:
        return False
    
    if account.balance < amount:
        return False
    
    # обработка
    return True
```

### Импорты

Используйте `isort` для сортировки импортов. Порядок:

1. Стандартная библиотека Python
2. Django и сторонние библиотеки
3. Локальные импорты проекта

```python
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.constants import PAGINATE_BY_DEFAULT
from hasta_la_vista_money.expense.models import Expense
```

---

## Обработка ошибок

### Кастомные исключения

Создавайте кастомные исключения для доменных ошибок:

```python
class AccountError(ValueError):
    """Base exception for account-related errors."""
    pass

class InsufficientFundsError(AccountError):
    """Raised when account has insufficient funds."""
    pass

class AccountNotFoundError(AccountError):
    """Raised when account is not found."""
    pass
```

### Использование исключений

Используйте конкретные исключения вместо общих:

```python
# ❌ Плохо
try:
    account = Account.objects.get(pk=account_id)
except Exception as e:
    return Response({'error': str(e)}, status=400)

# ✅ Хорошо
try:
    account = Account.objects.get(pk=account_id)
except Account.DoesNotExist:
    raise AccountNotFoundError(f'Account {account_id} not found')
except ValidationError as e:
    raise AccountError(f'Invalid account data: {e}')
```

### Сообщения об ошибках

Сообщения об ошибках должны быть понятными и информативными:

```python
# ❌ Плохо
raise ValueError('Error')

# ✅ Хорошо
raise InsufficientFundsError(
    f'Account {account.id} has balance {account.balance}, '
    f'but required {amount}'
)
```

---

## Тестирование

### Структура тестов

Тесты должны быть организованы по классам, соответствующим тестируемым классам:

```python
class TestExpenseService(TestCase):
    """Test cases for ExpenseService."""
    
    def setUp(self) -> None:
        """Set up test data."""
        self.user = UserFactory()
        self.account = AccountFactory(user=self.user)
        self.service = ExpenseService(...)
    
    def test_create_expense_success(self) -> None:
        """Test successful expense creation."""
        # Arrange
        amount = Decimal('100.00')
        
        # Act
        expense = self.service.create_expense(...)
        
        # Assert
        self.assertEqual(expense.amount, amount)
```

### Именование тестов

Имена тестов должны описывать, что тестируется:

```python
# ✅ Хорошо
def test_create_expense_success(self) -> None:
    pass

def test_create_expense_insufficient_funds(self) -> None:
    pass

def test_update_expense_changes_account_balance(self) -> None:
    pass
```

### Docstrings в тестах

Каждый тест должен иметь docstring, описывающий, что он проверяет:

```python
def test_create_expense_insufficient_funds(self) -> None:
    """Test that creating expense with insufficient funds raises error."""
    # ...
```

### Фикстуры

Используйте фикстуры для общих данных:

```python
@pytest.fixture
def user_account(db):
    """Create a user with an account for testing."""
    user = UserFactory()
    account = AccountFactory(user=user, balance=Decimal('1000.00'))
    return user, account
```

### Группировка тестов

Группируйте связанные тесты в отдельные классы:

```python
class TestExpenseServiceCreation(TestCase):
    """Test expense creation functionality."""
    pass

class TestExpenseServiceUpdate(TestCase):
    """Test expense update functionality."""
    pass

class TestExpenseServiceDeletion(TestCase):
    """Test expense deletion functionality."""
    pass
```

---

## Примеры

### Хороший пример сервиса

```python
"""Expense service for managing expenses."""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from hasta_la_vista_money.constants import PAGINATE_BY_DEFAULT
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User

class ExpenseService:
    """Service for managing expense operations."""
    
    def __init__(
        self,
        expense_repository: ExpenseRepository,
        account_service: AccountServiceProtocol,
    ):
        """Initialize expense service.
        
        Args:
            expense_repository: Repository for expense data access
            account_service: Service for account operations
        """
        self.expense_repository = expense_repository
        self.account_service = account_service
    
    def create_expense(
        self,
        user: 'User',
        account: Account,
        amount: Decimal,
        category: ExpenseCategory,
        date: date,
        notes: str | None = None,
    ) -> Expense:
        """Create a new expense record.
        
        Args:
            user: User who owns the expense
            account: Account from which the expense is made
            amount: Expense amount (must be positive)
            category: Expense category
            date: Date of the expense
            notes: Optional notes for the expense
            
        Returns:
            Created Expense instance
            
        Raises:
            ValidationError: If amount is negative or account balance
                is insufficient
        """
        self._validate_expense_data(user, account, amount)
        
        expense = self.expense_repository.create(
            user=user,
            account=account,
            amount=amount,
            category=category,
            date=date,
            notes=notes,
        )
        
        self.account_service.decrease_balance(account, amount)
        
        return expense
    
    def _validate_expense_data(
        self,
        user: 'User',
        account: Account,
        amount: Decimal,
    ) -> None:
        """Validate expense data before creation.
        
        Args:
            user: User who owns the expense
            account: Account to validate
            amount: Amount to validate
            
        Raises:
            ValidationError: If validation fails
        """
        if amount <= 0:
            raise ValidationError('Amount must be positive')
        
        if account.user != user:
            raise ValidationError('Account does not belong to user')
        
        if account.balance < amount:
            raise ValidationError('Insufficient funds')
```

### Хороший пример теста

```python
"""Tests for expense service."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from hasta_la_vista_money.expense.services.expense_services import (
    ExpenseService,
)
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.users.factories import UserFactory


class TestExpenseService(TestCase):
    """Test cases for ExpenseService."""
    
    def setUp(self) -> None:
        """Set up test data."""
        self.user = UserFactory()
        self.account = AccountFactory(
            user=self.user,
            balance=Decimal('1000.00'),
        )
        self.service = ExpenseService(...)
    
    def test_create_expense_success(self) -> None:
        """Test successful expense creation."""
        amount = Decimal('100.00')
        
        expense = self.service.create_expense(
            user=self.user,
            account=self.account,
            amount=amount,
            category=self.category,
            date=date.today(),
        )
        
        self.assertEqual(expense.amount, amount)
        self.assertEqual(expense.user, self.user)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
    
    def test_create_expense_insufficient_funds(self) -> None:
        """Test that creating expense with insufficient funds raises error."""
        amount = Decimal('2000.00')
        
        with self.assertRaises(ValidationError) as context:
            self.service.create_expense(
                user=self.user,
                account=self.account,
                amount=amount,
                category=self.category,
                date=date.today(),
            )
        
        self.assertIn('Insufficient funds', str(context.exception))
```

---

## Дополнительные ресурсы

- [PEP 8](https://pep8.org/) - Стиль кода Python
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Django Coding Style](https://docs.djangoproject.com/en/dev/internals/contributing/writing-code/coding-style/)
- [Type Hints PEP 484](https://www.python.org/dev/peps/pep-0484/)

---

## Примечания

Это руководство является живым документом и может обновляться по мере развития проекта. Если вы видите несоответствия или хотите предложить улучшения, создайте issue или pull request.

