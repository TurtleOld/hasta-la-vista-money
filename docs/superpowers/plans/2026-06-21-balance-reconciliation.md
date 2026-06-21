# Инструмент сверки баланса — План реализации

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ НАВЫК: используй `superpowers:subagent-driven-development` (рекомендуется) или `superpowers:executing-plans` для пошагового выполнения. Шаги используют синтаксис чекбоксов (`- [ ]`) для отслеживания прогресса.

**Цель:** Добавить умную категоризацию транзакций через LLM, извлечение конечного остатка из выписки и экран сверки баланса после импорта.

**Архитектура:** Парсинг PDF остаётся локальным (camelot/pdfminer). Добавляется шаг очистки PII и вызова LLM для категоризации через OpenAI-совместимый API (поддерживает LM Studio, Ollama, Claude, OpenAI). После импорта конечный остаток из выписки сравнивается с `Account.balance` — расхождение сохраняется в `BankStatementUpload` и отображается в UI.

**Стек:** Django, dependency-injector, httpx, camelot-py, pdfminer-six, python-decouple, Tailwind CSS.

## Глобальные ограничения

- Python 3.12+, Django 6.x
- Настройки читаются через `decouple.config()`
- DI через `dependency_injector` (`providers.Singleton` / `providers.Factory`)
- Тесты: `django.test.TestCase` + `unittest.mock.patch`
- Новая миграция нумеруется `0010_...`
- Все строки UI — через `gettext_lazy` / `{% translate %}`
- CSV/Excel не затрагиваются — только PDF

---

## Карта файлов

| Действие | Файл |
|----------|------|
| Создать  | `hasta_la_vista_money/users/services/pii_stripper.py` |
| Создать  | `hasta_la_vista_money/users/services/category_classifier.py` |
| Создать  | `hasta_la_vista_money/users/tests/test_pii_stripper.py` |
| Создать  | `hasta_la_vista_money/users/tests/test_category_classifier.py` |
| Изменить | `hasta_la_vista_money/users/services/bank_statement.py` |
| Изменить | `hasta_la_vista_money/users/models.py` |
| Создать  | `hasta_la_vista_money/users/migrations/0010_bankstatementupload_reconciliation.py` |
| Изменить | `hasta_la_vista_money/users/tasks.py` |
| Изменить | `hasta_la_vista_money/users/containers.py` |
| Изменить | `hasta_la_vista_money/users/views/bank_statement.py` |
| Изменить | `hasta_la_vista_money/users/templates/users/bank_statement_upload.html` |
| Изменить | `static/js/bank-statement-upload.js` |
| Изменить | `config/django/base.py` |
| Изменить | `config/containers.py` |

---

## Задача 1: PII-стриппер

**Файлы:**
- Создать: `hasta_la_vista_money/users/services/pii_stripper.py`
- Создать: `hasta_la_vista_money/users/tests/test_pii_stripper.py`

**Интерфейс:**
- Производит: `strip_pii(description: str) -> str`

- [ ] **Шаг 1: Написать падающий тест**

```python
# hasta_la_vista_money/users/tests/test_pii_stripper.py
from django.test import TestCase
from hasta_la_vista_money.users.services.pii_stripper import strip_pii


class TestStripPii(TestCase):
    def test_removes_masked_card(self):
        assert strip_pii("Оплата *4321 MAGNIT") == "Оплата MAGNIT"

    def test_removes_auth_code(self):
        # standalone 5-7 digit number
        assert strip_pii("NETFLIX.COM 123456") == "NETFLIX.COM"

    def test_removes_date_fragment(self):
        assert strip_pii("SPAR 12.03.2025 Москва") == "SPAR Москва"

    def test_preserves_clean_description(self):
        assert strip_pii("Продукты питания") == "Продукты питания"

    def test_collapses_extra_spaces(self):
        assert strip_pii("Яндекс  Такси  *1234") == "Яндекс Такси"

    def test_empty_string(self):
        assert strip_pii("") == ""
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_pii_stripper.py -v
```
Ожидается: `ImportError` или `ModuleNotFoundError`

- [ ] **Шаг 3: Реализовать `strip_pii`**

```python
# hasta_la_vista_money/users/services/pii_stripper.py
import re

_CARD_MASK = re.compile(r'\*\d{2,6}')
_AUTH_CODE = re.compile(r'\b\d{5,7}\b')
_DATE_FRAGMENT = re.compile(r'\b\d{2}\.\d{2}\.\d{4}\b')
_MULTI_SPACE = re.compile(r' {2,}')


def strip_pii(description: str) -> str:
    """Удалить из описания операции данные, которые не должны покидать сервер.

    Убирает: маски карт (*1234), коды авторизации (5–7 цифр подряд),
    фрагменты дат (DD.MM.YYYY). Оставляет: название магазина / контрагента.
    """
    result = _CARD_MASK.sub('', description)
    result = _DATE_FRAGMENT.sub('', result)
    result = _AUTH_CODE.sub('', result)
    result = _MULTI_SPACE.sub(' ', result)
    return result.strip()
```

- [ ] **Шаг 4: Прогнать тесты — должны пройти**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_pii_stripper.py -v
```
Ожидается: все тесты `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add hasta_la_vista_money/users/services/pii_stripper.py \
        hasta_la_vista_money/users/tests/test_pii_stripper.py
git commit -m "feat(users): add PII stripper for bank statement descriptions"
```

---

## Задача 2: CategoryClassifier — протокол и заглушка

**Файлы:**
- Создать: `hasta_la_vista_money/users/services/category_classifier.py`
- Создать: `hasta_la_vista_money/users/tests/test_category_classifier.py`

**Интерфейс:**
- Производит:
  ```python
  class CategoryClassifier(Protocol):
      def classify(
          self,
          description: str,
          transaction_type: str,  # "income" | "expense"
          existing_categories: list[str],
      ) -> str: ...

  class NoopClassifier:
      def classify(self, description, transaction_type, existing_categories) -> str: ...

  class OpenAICompatibleClassifier:
      def __init__(self, base_url: str, api_key: str, model: str) -> None: ...
      def classify(self, description, transaction_type, existing_categories) -> str: ...
  ```

- [ ] **Шаг 1: Написать падающие тесты**

```python
# hasta_la_vista_money/users/tests/test_category_classifier.py
from unittest.mock import MagicMock, patch
from django.test import TestCase
from hasta_la_vista_money.users.services.category_classifier import (
    NoopClassifier,
    OpenAICompatibleClassifier,
)


class TestNoopClassifier(TestCase):
    def test_returns_description_unchanged(self):
        clf = NoopClassifier()
        result = clf.classify(
            description="MAGNIT",
            transaction_type="expense",
            existing_categories=["Продукты", "Транспорт"],
        )
        assert result == "MAGNIT"

    def test_returns_description_when_no_categories(self):
        clf = NoopClassifier()
        result = clf.classify("ЗП", "income", [])
        assert result == "ЗП"


class TestOpenAICompatibleClassifier(TestCase):
    def _make_clf(self):
        return OpenAICompatibleClassifier(
            base_url="http://localhost:1234/v1",
            api_key="",
            model="llama3",
        )

    @patch("hasta_la_vista_money.users.services.category_classifier.httpx.Client")
    def test_returns_category_from_llm(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Продукты"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify("MAGNIT", "expense", ["Продукты", "Транспорт"])
        assert result == "Продукты"

    @patch("hasta_la_vista_money.users.services.category_classifier.httpx.Client")
    def test_falls_back_to_description_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify("NETFLIX.COM", "expense", [])
        assert result == "NETFLIX.COM"

    @patch("hasta_la_vista_money.users.services.category_classifier.httpx.Client")
    def test_strips_whitespace_from_llm_response(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "  Транспорт  "}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify("Яндекс Такси", "expense", ["Транспорт"])
        assert result == "Транспорт"
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_category_classifier.py -v
```
Ожидается: `ImportError`

- [ ] **Шаг 3: Реализовать классы**

```python
# hasta_la_vista_money/users/services/category_classifier.py
import logging
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты помощник по категоризации финансовых операций. "
    "Пользователь даст тебе описание операции, её тип (доход/расход) "
    "и список уже существующих категорий. "
    "Верни ОДНО слово или короткую фразу — название категории. "
    "Если подходит существующая категория — используй её. "
    "Иначе придумай короткое осмысленное название. "
    "Отвечай только названием категории, без пояснений."
)


@runtime_checkable
class CategoryClassifier(Protocol):
    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str: ...


class NoopClassifier:
    """Заглушка: возвращает описание как есть. Используется когда LLM не настроен."""

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        return description


class OpenAICompatibleClassifier:
    """Категоризатор через OpenAI-совместимый API (LM Studio, Ollama, Claude, OpenAI)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._model = model

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        type_label = "доход" if transaction_type == "income" else "расход"
        cats = ", ".join(existing_categories) if existing_categories else "нет"
        user_message = (
            f"Операция: {description}\n"
            f"Тип: {type_label}\n"
            f"Существующие категории: {cats}"
        )
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": 20,
            "temperature": 0,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            logger.warning(
                "category_classifier_failed",
                description=description,
                exc_info=True,
            )
            return description
```

- [ ] **Шаг 4: Прогнать тесты**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_category_classifier.py -v
```
Ожидается: все тесты `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add hasta_la_vista_money/users/services/category_classifier.py \
        hasta_la_vista_money/users/tests/test_category_classifier.py
git commit -m "feat(users): add CategoryClassifier with NoopClassifier and OpenAI-compatible backend"
```

---

## Задача 3: Настройки и DI-контейнер

**Файлы:**
- Изменить: `config/django/base.py`
- Изменить: `hasta_la_vista_money/users/containers.py`
- Изменить: `config/containers.py`

**Интерфейс:**
- Потребляет: `NoopClassifier`, `OpenAICompatibleClassifier` из задачи 2
- Производит: `ApplicationContainer().users.category_classifier()` → объект, реализующий `CategoryClassifier`

- [ ] **Шаг 1: Добавить настройки в `config/django/base.py`**

Найти блок с переменными окружения (после `SECRET_KEY`) и добавить в конец файла:

```python
# Категоризация транзакций через LLM
# Если CATEGORY_CLASSIFIER_BASE_URL пуст — используется NoopClassifier
CATEGORY_CLASSIFIER_BASE_URL: str = config(
    'CATEGORY_CLASSIFIER_BASE_URL', default=''
)
CATEGORY_CLASSIFIER_API_KEY: str = config(
    'CATEGORY_CLASSIFIER_API_KEY', default=''
)
CATEGORY_CLASSIFIER_MODEL: str = config(
    'CATEGORY_CLASSIFIER_MODEL', default=''
)
```

- [ ] **Шаг 2: Обновить `hasta_la_vista_money/users/containers.py`**

```python
"""Dependency injection container for users application."""

from dependency_injector import containers, providers
from django.conf import settings

from hasta_la_vista_money.users.protocols.services import (
    UserStatisticsServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.category_classifier import (
    NoopClassifier,
    OpenAICompatibleClassifier,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatisticsService,
)


def _build_classifier():
    base_url = getattr(settings, 'CATEGORY_CLASSIFIER_BASE_URL', '')
    if not base_url:
        return NoopClassifier()
    return OpenAICompatibleClassifier(
        base_url=base_url,
        api_key=getattr(settings, 'CATEGORY_CLASSIFIER_API_KEY', ''),
        model=getattr(settings, 'CATEGORY_CLASSIFIER_MODEL', ''),
    )


class UsersContainer(containers.DeclarativeContainer):
    """DI-контейнер для приложения users."""

    statistics_repository = providers.Singleton(StatisticsRepository)

    user_statistics_service: providers.Factory[
        UserStatisticsServiceProtocol
    ] = providers.Factory(
        UserStatisticsService,
        statistics_repository=statistics_repository,
    )

    category_classifier = providers.Singleton(_build_classifier)
```

- [ ] **Шаг 3: Проверить, что приложение запускается**

```bash
python manage.py check
```
Ожидается: `System check identified no issues.`

- [ ] **Шаг 4: Коммит**

```bash
git add config/django/base.py \
        hasta_la_vista_money/users/containers.py
git commit -m "feat(users): wire CategoryClassifier into DI container via settings"
```

---

## Задача 4: `StatementParseResult` и извлечение конечного остатка

**Файлы:**
- Изменить: `hasta_la_vista_money/users/services/bank_statement.py`

**Интерфейс:**
- Производит:
  ```python
  @dataclass
  class StatementParseResult:
      transactions: list[dict[str, Any]]
      closing_balance: Decimal | None
      closing_balance_date: date | None
  ```
  `BankStatementParser.parse()` → `StatementParseResult`

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в `hasta_la_vista_money/users/tests/test_bank_statement_upload.py` в конец файла:

```python
from hasta_la_vista_money.users.services.bank_statement import StatementParseResult


class TestStatementParseResult(TestCase):
    """Тест структуры результата парсинга."""

    def test_has_expected_fields(self):
        result = StatementParseResult(
            transactions=[],
            closing_balance=Decimal('12345.67'),
            closing_balance_date=None,
        )
        assert result.transactions == []
        assert result.closing_balance == Decimal('12345.67')
        assert result.closing_balance_date is None

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    @patch('hasta_la_vista_money.users.services.bank_statement.extract_text')
    def test_parse_returns_statement_parse_result(
        self, mock_extract_text, mock_camelot
    ):
        mock_extract_text.return_value = 'Райффайзенбанк'
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame()
        mock_camelot.read_pdf.return_value = [mock_table]

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4 fake')
            path = f.name

        try:
            parser = BankStatementParser(path)
            result = parser.parse()
            assert isinstance(result, StatementParseResult)
            assert isinstance(result.transactions, list)
        finally:
            Path(path).unlink(missing_ok=True)
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py::TestStatementParseResult -v
```
Ожидается: `ImportError` для `StatementParseResult`

- [ ] **Шаг 3: Добавить `StatementParseResult` в `bank_statement.py`**

В начало файла после импортов добавить:

```python
from dataclasses import dataclass, field
from datetime import date as date_type


@dataclass
class StatementParseResult:
    transactions: list[dict[str, Any]]
    closing_balance: Decimal | None = None
    closing_balance_date: date_type | None = None
```

- [ ] **Шаг 4: Добавить `_extract_closing_balance` в `BaseBankStatementParser`**

Добавить метод в класс `BaseBankStatementParser` после `_clean_description`:

```python
def _extract_closing_balance(self, full_text: str) -> Decimal | None:
    """Попытаться извлечь конечный остаток из текста выписки.

    Ищет паттерны вида:
    - 'Исходящий остаток ... 12 345,67'
    - 'Остаток на конец ... 12 345,67'
    - 'Closing balance ... 12,345.67'
    """
    patterns = [
        r'(?:Исходящий остаток|Остаток на конец периода|Остаток на конец'
        r'|Конечный остаток|Closing balance)'
        r'[^\d\-]*([+-]?\s*\d[\d\s\xa0]*[,\.]\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            raw = (
                match.group(1)
                .replace('\xa0', '')
                .replace(' ', '')
                .replace(',', '.')
            )
            try:
                return Decimal(raw)
            except InvalidOperation:
                continue
    return None
```

- [ ] **Шаг 5: Изменить сигнатуру `parse()` у `_GenericBankParser`**

Заменить метод `parse` в `_GenericBankParser`:

```python
def parse(self) -> StatementParseResult:
    try:
        logger.info('Starting PDF parsing (generic): %s', self.pdf_path)
        full_text = extract_text(str(self.pdf_path))
        tables = self._read_tables()
        logger.info('Found %d tables in PDF', len(tables))
        transactions: list[dict[str, Any]] = []

        for idx, table in enumerate(tables):
            logger.info('Processing table %d/%d', idx + 1, len(tables))
            table_df = table.df
            if len(
                table_df.columns,
            ) >= MIN_TABLE_COLUMNS and self._is_transaction_table(table_df):
                parsed = self._parse_table(table_df)
                logger.info(
                    'Extracted %d transactions from table %d',
                    len(parsed),
                    idx + 1,
                )
                transactions.extend(parsed)

        transactions = [t for t in transactions if t['amount'] != Decimal(0)]
        transactions = _dedup_transactions(transactions)
        closing_balance = self._extract_closing_balance(full_text)

        logger.info(
            'Parsing complete. Total: %d transactions, closing_balance=%s',
            len(transactions),
            closing_balance,
        )
    except BankStatementParseError:
        raise
    except Exception as e:
        logger.exception('Failed to parse PDF: %s', self.pdf_path)
        error_msg = f'Не удалось обработать PDF файл: {e!s}'
        raise BankStatementParseError(error_msg) from e
    else:
        return StatementParseResult(
            transactions=transactions,
            closing_balance=closing_balance,
        )
```

- [ ] **Шаг 6: Обновить `_SberbankParser.parse()` аналогично**

Заменить возвращаемый тип и финальный `return` в `_SberbankParser.parse()`:

```python
def parse(self) -> StatementParseResult:
    try:
        logger.info('Starting PDF parsing (Sberbank): %s', self.pdf_path)
        full_text = extract_text(str(self.pdf_path))
        tables = self._read_tables()
        logger.info('Found %d tables in PDF', len(tables))
        transactions: list[dict[str, Any]] = []

        for idx, table in enumerate(tables):
            logger.info('Processing table %d/%d', idx + 1, len(tables))
            table_df = table.df
            if len(
                table_df.columns,
            ) >= MIN_SBERBANK_COLUMNS and self._is_transaction_table(table_df):
                parsed = self._parse_table(table_df)
                logger.info(
                    'Extracted %d transactions from table %d',
                    len(parsed),
                    idx + 1,
                )
                transactions.extend(parsed)

        transactions = [t for t in transactions if t['amount'] != Decimal(0)]
        transactions = _dedup_transactions(transactions)
        closing_balance = self._extract_closing_balance(full_text)

        logger.info(
            'Parsing complete. Total: %d (after dedup), closing_balance=%s',
            len(transactions),
            closing_balance,
        )
    except BankStatementParseError:
        raise
    except Exception as e:
        logger.exception('Failed to parse PDF: %s', self.pdf_path)
        error_msg = f'Не удалось обработать PDF файл: {e!s}'
        raise BankStatementParseError(error_msg) from e
    else:
        return StatementParseResult(
            transactions=transactions,
            closing_balance=closing_balance,
        )
```

- [ ] **Шаг 6б: Обновить аннотацию `_RaiffeisenBankParser.parse()`**

`_RaiffeisenBankParser.parse()` только вызывает `super().parse()` — достаточно изменить аннотацию возвращаемого типа:

```python
def parse(self) -> StatementParseResult:
    logger.info('Starting PDF parsing (Raiffeisen): %s', self.pdf_path)
    return super().parse()
```

- [ ] **Шаг 7: Обновить публичный фасад `BankStatementParser.parse()`**

```python
def parse(self) -> StatementParseResult:
    """Разобрать PDF и вернуть StatementParseResult."""
    return self._delegate.parse()
```

- [ ] **Шаг 8: Прогнать тесты**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py -v
```
Ожидается: все тесты `PASSED` (существующие адаптируются автоматически, так как `result.transactions` совместим)

> **Важно:** если в существующих тестах есть `parser.parse()` возвращающий `list`, обновить их — заменить `transactions = parser.parse()` на `result = parser.parse(); transactions = result.transactions`.

- [ ] **Шаг 9: Коммит**

```bash
git add hasta_la_vista_money/users/services/bank_statement.py \
        hasta_la_vista_money/users/tests/test_bank_statement_upload.py
git commit -m "feat(users): add StatementParseResult and closing balance extraction"
```

---

## Задача 5: Миграция — новые поля в `BankStatementUpload`

**Файлы:**
- Изменить: `hasta_la_vista_money/users/models.py`
- Создать: `hasta_la_vista_money/users/migrations/0010_bankstatementupload_reconciliation.py`

**Интерфейс:**
- Производит поля: `statement_closing_balance`, `account_balance_after`, `balance_discrepancy` на модели `BankStatementUpload`

- [ ] **Шаг 1: Добавить поля в модель**

В `hasta_la_vista_money/users/models.py` в класс `BankStatementUpload` после поля `skipped_count` добавить:

```python
statement_closing_balance = DecimalField(
    max_digits=20,
    decimal_places=2,
    null=True,
    blank=True,
    verbose_name=_('Остаток по выписке'),
)
account_balance_after = DecimalField(
    max_digits=20,
    decimal_places=2,
    null=True,
    blank=True,
    verbose_name=_('Остаток в приложении после импорта'),
)
balance_discrepancy = DecimalField(
    max_digits=20,
    decimal_places=2,
    null=True,
    blank=True,
    verbose_name=_('Расхождение баланса'),
)
```

Также добавить импорт `DecimalField` в начало файла (уже импортированы другие django.db.models поля; добавить `DecimalField` к ним).

- [ ] **Шаг 2: Создать миграцию**

```bash
python manage.py makemigrations users --name bankstatementupload_reconciliation
```
Ожидается: файл `0010_bankstatementupload_reconciliation.py`

- [ ] **Шаг 3: Применить миграцию**

```bash
python manage.py migrate
```
Ожидается: `OK`

- [ ] **Шаг 4: Проверить `manage.py check`**

```bash
python manage.py check
```
Ожидается: `System check identified no issues.`

- [ ] **Шаг 5: Коммит**

```bash
git add hasta_la_vista_money/users/models.py \
        hasta_la_vista_money/users/migrations/0010_bankstatementupload_reconciliation.py
git commit -m "feat(users): add reconciliation fields to BankStatementUpload"
```

---

## Задача 6: Интеграция в пайплайн — категоризация и сверка

**Файлы:**
- Изменить: `hasta_la_vista_money/users/tasks.py`

**Интерфейс:**
- Потребляет:
  - `strip_pii(description: str) -> str` из задачи 1
  - `CategoryClassifier.classify(description, transaction_type, existing_categories) -> str` из задачи 2
  - `StatementParseResult` из задачи 4
  - Поля `statement_closing_balance`, `account_balance_after`, `balance_discrepancy` из задачи 5

- [ ] **Шаг 1: Написать падающий тест**

Добавить в `hasta_la_vista_money/users/tests/test_bank_statement_upload.py`:

```python
from unittest.mock import MagicMock
from hasta_la_vista_money.users.services.category_classifier import NoopClassifier
from hasta_la_vista_money.users.services.bank_statement import StatementParseResult


class TestProcessTransactionsWithClassifier(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тест',
            balance=Decimal('10000.00'),
            currency='RUB',
        )

    @patch('hasta_la_vista_money.users.tasks.BankStatementParser')
    @patch('hasta_la_vista_money.users.tasks.ApplicationContainer')
    def test_category_uses_classifier_output(
        self, mock_container_cls, mock_parser_cls
    ):
        from hasta_la_vista_money.users.tasks import process_bank_statement_task
        from django.utils import timezone

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 'Продукты'
        mock_container = MagicMock()
        mock_container.users.category_classifier.return_value = mock_classifier
        mock_container_cls.return_value = mock_container

        mock_parser = MagicMock()
        mock_parser.parse.return_value = StatementParseResult(
            transactions=[{
                'date': timezone.now(),
                'amount': Decimal('-500.00'),
                'description': 'MAGNIT 1234',
                'source_ref': 'ref-001',
            }],
            closing_balance=Decimal('9500.00'),
        )
        mock_parser_cls.return_value = mock_parser

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/test.pdf',
            status=BankStatementUpload.Status.PENDING,
        )
        # Вызвать синхронно (без Celery)
        process_bank_statement_task.__wrapped__(None, upload.pk)

        upload.refresh_from_db()
        assert upload.status == BankStatementUpload.Status.COMPLETED
        assert upload.statement_closing_balance == Decimal('9500.00')

        category = Category.objects.filter(
            user=self.user, name='Продукты'
        ).first()
        assert category is not None
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py::TestProcessTransactionsWithClassifier -v
```
Ожидается: `FAILED` (нет `ApplicationContainer` импорта / нет логики категоризации)

- [ ] **Шаг 3: Обновить `tasks.py`**

Полностью заменить файл:

```python
"""Celery tasks for user-related async operations."""

import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.db.models import F

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
)
from hasta_la_vista_money.users.services.pii_stripper import strip_pii

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_bank_statement_task(
    self: shared_task,  # type: ignore[valid-type]
    upload_id: int,
) -> dict[str, int]:
    """Обработать PDF-выписку в фоне: импортировать транзакции и сверить баланс."""
    logger.info(
        'Starting bank statement processing task for upload_id=%d',
        upload_id,
    )

    try:
        upload = BankStatementUpload.objects.select_related(
            'user', 'account'
        ).get(id=upload_id)
        _initialize_upload(upload, self)

        classifier = ApplicationContainer().users.category_classifier()

        logger.info('Processing upload: %s', upload.pdf_file.path)
        parser = BankStatementParser(upload.pdf_file.path)
        parse_result = parser.parse()
        transactions = parse_result.transactions

        upload.total_transactions = len(transactions)
        upload.save(update_fields=['total_transactions'])

        logger.info('Found %d transactions to process', len(transactions))

        existing_categories = list(
            Category.objects.filter(user=upload.user)
            .values_list('name', flat=True)
            .distinct()
        )

        income_count, expense_count, skipped_count = _process_transactions(
            upload=upload,
            transactions=transactions,
            classifier=classifier,
            existing_categories=existing_categories,
        )

        # Сверка баланса
        upload.account.refresh_from_db(fields=['balance'])
        if parse_result.closing_balance is not None:
            upload.statement_closing_balance = parse_result.closing_balance
            upload.account_balance_after = upload.account.balance
            upload.balance_discrepancy = (
                parse_result.closing_balance - upload.account.balance
            )

        upload.status = BankStatementUpload.Status.COMPLETED
        upload.progress = 100
        upload.save(update_fields=[
            'status', 'progress',
            'statement_closing_balance',
            'account_balance_after',
            'balance_discrepancy',
        ])

        logger.info(
            'Completed: %d income, %d expenses, %d skipped, discrepancy=%s',
            income_count,
            expense_count,
            skipped_count,
            upload.balance_discrepancy,
        )

        return {
            'income_count': income_count,
            'expense_count': expense_count,
            'skipped_count': skipped_count,
            'total_count': income_count + expense_count,
        }

    except BankStatementUpload.DoesNotExist:
        logger.exception('Upload with id=%d not found', upload_id)
        raise

    except BankStatementParseError as e:
        logger.exception('Failed to parse bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Ошибка парсинга: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
        except BankStatementUpload.DoesNotExist:
            pass
        raise

    except Exception as e:
        logger.exception('Unexpected error processing bank statement')
        try:
            upload = BankStatementUpload.objects.get(id=upload_id)
            upload.status = BankStatementUpload.Status.FAILED
            upload.error_message = f'Непредвиденная ошибка: {e!s}'
            upload.save(update_fields=['status', 'error_message'])
        except BankStatementUpload.DoesNotExist:
            pass
        raise self.retry(exc=e, countdown=60) from e


def _initialize_upload(upload: BankStatementUpload, task) -> None:
    upload.status = BankStatementUpload.Status.PROCESSING
    upload.celery_task_id = task.request.id
    upload.progress = 0
    upload.save(update_fields=['status', 'celery_task_id', 'progress'])


def _process_transactions(
    upload: BankStatementUpload,
    transactions: list[dict],
    classifier,
    existing_categories: list[str],
) -> tuple[int, int, int]:
    income_count = 0
    expense_count = 0
    skipped_count = 0
    batch_size = 10
    total = len(transactions)

    for idx, trans in enumerate(transactions):
        with transaction.atomic():
            amount = trans['amount']
            description = trans['description']
            trans_date = trans['date']
            source_ref = trans.get('source_ref')
            abs_amount = abs(amount)

            if amount > 0:
                type_value = TransactionType.INCOME
                balance_change = abs_amount
            else:
                type_value = TransactionType.EXPENSE
                balance_change = -abs_amount

            if _is_duplicate(
                account=upload.account,
                user=upload.user,
                type_value=type_value,
                abs_amount=abs_amount,
                trans_date=trans_date,
                source_ref=source_ref,
            ):
                skipped_count += 1
                created = False
            else:
                clean_desc = strip_pii(description)
                category_name = classifier.classify(
                    description=clean_desc,
                    transaction_type=type_value,
                    existing_categories=existing_categories,
                )
                if category_name not in existing_categories:
                    existing_categories.append(category_name)

                category, _ = Category.objects.get_or_create(
                    user=upload.user,
                    name=category_name[:250],
                    type=type_value,
                )
                Transaction.objects.create(
                    user=upload.user,
                    account=upload.account,
                    category=category,
                    type=type_value,
                    amount=abs_amount,
                    date=trans_date,
                    source_ref=source_ref or None,
                )
                created = True

            if created:
                Account.objects.filter(pk=upload.account.pk).update(
                    balance=F('balance') + balance_change,
                )
                if type_value == TransactionType.INCOME:
                    income_count += 1
                else:
                    expense_count += 1

        upload.processed_transactions = idx + 1
        upload.income_count = income_count
        upload.expense_count = expense_count
        upload.skipped_count = skipped_count
        upload.progress = int((idx + 1) / total * 100)

        if (idx + 1) % batch_size == 0 or idx == total - 1:
            upload.save(update_fields=[
                'processed_transactions',
                'income_count',
                'expense_count',
                'skipped_count',
                'progress',
            ])
            logger.info(
                'Progress: %d/%d (%d%%)',
                idx + 1,
                total,
                upload.progress,
            )

    return income_count, expense_count, skipped_count


def _is_duplicate(
    *,
    account: Account,
    user,
    type_value: str,
    abs_amount,
    trans_date,
    source_ref: str | None,
) -> bool:
    if source_ref:
        if Transaction.objects.filter(
            account=account,
            source_ref=source_ref,
        ).exists():
            return True
        legacy = Transaction.objects.filter(
            account=account,
            user=user,
            type=type_value,
            amount=abs_amount,
            date=trans_date,
            source_ref__isnull=True,
        ).first()
        if legacy is not None:
            legacy.source_ref = source_ref
            legacy.save(update_fields=['source_ref'])
            return True
        return False
    return Transaction.objects.filter(
        account=account,
        user=user,
        type=type_value,
        amount=abs_amount,
        date=trans_date,
        source_ref__isnull=True,
    ).exists()
```

- [ ] **Шаг 4: Прогнать тесты**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py -v
```
Ожидается: все тесты `PASSED`

- [ ] **Шаг 5: Коммит**

```bash
git add hasta_la_vista_money/users/tasks.py
git commit -m "feat(users): integrate LLM categorization and balance reconciliation into import pipeline"
```

---

## Задача 7: API статуса и шаблон сверки

**Файлы:**
- Изменить: `hasta_la_vista_money/users/views/bank_statement.py`
- Изменить: `hasta_la_vista_money/users/templates/users/bank_statement_upload.html`
- Изменить: `static/js/bank-statement-upload.js`

**Интерфейс:**
- Потребляет поля `statement_closing_balance`, `account_balance_after`, `balance_discrepancy` из задачи 5

- [ ] **Шаг 1: Написать тест для JSON-ответа статуса**

Добавить в `hasta_la_vista_money/users/tests/test_bank_statement_upload.py`:

```python
class TestBankStatementUploadStatusReconciliation(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self):
        self.user = User.objects.get(pk=1)
        self.client = Client()
        self.client.force_login(self.user)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тест',
            balance=Decimal('45230.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/test.pdf',
            status=BankStatementUpload.Status.COMPLETED,
            statement_closing_balance=Decimal('45230.00'),
            account_balance_after=Decimal('45230.00'),
            balance_discrepancy=Decimal('0.00'),
        )

    def test_status_includes_reconciliation_fields(self):
        url = reverse('users:bank_statement_upload_status', args=[self.upload.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('statement_closing_balance', data)
        self.assertIn('account_balance_after', data)
        self.assertIn('balance_discrepancy', data)
        self.assertEqual(data['balance_discrepancy'], '0.00')

    def test_status_discrepancy_nonzero(self):
        self.upload.statement_closing_balance = Decimal('45230.00')
        self.upload.account_balance_after = Decimal('44730.00')
        self.upload.balance_discrepancy = Decimal('500.00')
        self.upload.save()

        url = reverse('users:bank_statement_upload_status', args=[self.upload.pk])
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(data['balance_discrepancy'], '500.00')
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py::TestBankStatementUploadStatusReconciliation -v
```
Ожидается: `AssertionError` — поля отсутствуют в ответе

- [ ] **Шаг 3: Обновить `BankStatementUploadStatusView`**

В `hasta_la_vista_money/users/views/bank_statement.py` заменить `return JsonResponse(...)` блок:

```python
return JsonResponse(
    {
        'status': upload.status,
        'progress': upload.progress,
        'total_transactions': upload.total_transactions,
        'processed_transactions': upload.processed_transactions,
        'income_count': upload.income_count,
        'expense_count': upload.expense_count,
        'skipped_count': upload.skipped_count,
        'error_message': upload.error_message,
        'statement_closing_balance': (
            str(upload.statement_closing_balance)
            if upload.statement_closing_balance is not None
            else None
        ),
        'account_balance_after': (
            str(upload.account_balance_after)
            if upload.account_balance_after is not None
            else None
        ),
        'balance_discrepancy': (
            str(upload.balance_discrepancy)
            if upload.balance_discrepancy is not None
            else None
        ),
    },
)
```

- [ ] **Шаг 4: Прогнать тест API**

```bash
python -m pytest hasta_la_vista_money/users/tests/test_bank_statement_upload.py::TestBankStatementUploadStatusReconciliation -v
```
Ожидается: `PASSED`

- [ ] **Шаг 5: Добавить блок сверки в шаблон**

В `bank_statement_upload.html` сразу после закрывающего `</div>` блока `progressIndicator` (строка ~147) добавить:

```html
<!-- Блок сверки баланса — показывается после завершения -->
<div id="reconciliationBlock" class="hidden mt-6 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
    <div class="p-6">
        <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
            <i class="bi bi-bar-chart-line mr-2"></i>
            {% translate 'Результат сверки' %}
        </h3>
        <dl class="space-y-2 text-sm">
            <div class="flex justify-between">
                <dt class="text-gray-600 dark:text-gray-400">{% translate 'Остаток по выписке' %}</dt>
                <dd id="statementBalance" class="font-medium text-gray-900 dark:text-white">—</dd>
            </div>
            <div class="flex justify-between">
                <dt class="text-gray-600 dark:text-gray-400">{% translate 'Остаток в приложении' %}</dt>
                <dd id="accountBalance" class="font-medium text-gray-900 dark:text-white">—</dd>
            </div>
            <div class="flex justify-between border-t border-gray-200 dark:border-gray-700 pt-2 mt-2">
                <dt class="font-medium text-gray-700 dark:text-gray-300">{% translate 'Расхождение' %}</dt>
                <dd id="balanceDiscrepancy" class="font-semibold">—</dd>
            </div>
        </dl>
    </div>
</div>
```

- [ ] **Шаг 6: Обновить JS для отображения блока сверки**

В `static/js/bank-statement-upload.js` найти блок `} else if (data.status === 'completed') {` (строка ~218) и добавить после существующего кода отображения статуса:

```javascript
// Показать блок сверки
if (
    data.statement_closing_balance !== null ||
    data.account_balance_after !== null
) {
    const reconcBlock = document.getElementById('reconciliationBlock');
    if (reconcBlock) {
        reconcBlock.classList.remove('hidden');

        const fmt = (val) =>
            val !== null
                ? parseFloat(val).toLocaleString('ru-RU', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                  }) + ' ₽'
                : '—';

        document.getElementById('statementBalance').textContent =
            fmt(data.statement_closing_balance);
        document.getElementById('accountBalance').textContent =
            fmt(data.account_balance_after);

        const discEl = document.getElementById('balanceDiscrepancy');
        const disc = parseFloat(data.balance_discrepancy || '0');
        discEl.textContent = fmt(data.balance_discrepancy);
        if (Math.abs(disc) < 0.01) {
            discEl.classList.add('text-green-600', 'dark:text-green-400');
            discEl.textContent += ' ✓';
        } else {
            discEl.classList.add('text-red-600', 'dark:text-red-400');
        }
    }
}
```

- [ ] **Шаг 7: Прогнать все тесты**

```bash
python -m pytest hasta_la_vista_money/users/tests/ -v
```
Ожидается: все тесты `PASSED`

- [ ] **Шаг 8: Коммит**

```bash
git add hasta_la_vista_money/users/views/bank_statement.py \
        hasta_la_vista_money/users/templates/users/bank_statement_upload.html \
        static/js/bank-statement-upload.js
git commit -m "feat(users): add reconciliation summary to bank statement upload UI"
```

---

## Финальная проверка

- [ ] Прогнать все тесты проекта

```bash
python -m pytest --tb=short -q
```
Ожидается: все `PASSED`, 0 ошибок

- [ ] Проверить `manage.py check`

```bash
python manage.py check
```
Ожидается: `System check identified no issues.`

- [ ] Финальный коммит (если остались unstaged изменения)

```bash
git status
```
