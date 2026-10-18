"""Service for parsing bank statements from PDF files.

Supports multiple bank formats with auto-detection:
- Raiffeisen (Райффайзенбанк)
- Sberbank credit card (Выписка по счёту кредитной карты)
- Ozon Bank (Справка о движении средств)
- RosDorBank (ПАО "РосДорБанк", Выписка по счету)
- Generic Russian bank format (fallback)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import camelot
import structlog
from django.utils import timezone
from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer, LTTextLine
from pdfminer.pdfparser import PDFSyntaxError

from hasta_la_vista_money.transactions.models import Category

if TYPE_CHECKING:
    import pandas as pd

    from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


@dataclass
class StatementParseResult:
    """Результат разбора банковской выписки.

    Attributes:
        transactions: Список распознанных операций. Каждый элемент содержит
            ключи ``date``, ``amount``, ``description`` и опционально
            ``source_ref``.
        closing_balance: Конечный остаток по выписке, если удалось извлечь.
        closing_balance_date: Дата конечного остатка, если известна.
        account_number: Номер счёта из шапки выписки, если есть.
        period_start: Начало периода выписки, если известно.
    """

    transactions: list[dict[str, Any]] = field(default_factory=list)
    closing_balance: Decimal | None = None
    closing_balance_date: date_type | None = None
    account_number: str | None = None
    period_start: date_type | None = None


# General parsing constants
MIN_TABLE_COLUMNS = 5
MIN_STANDARD_COLUMNS = 7
MIN_YEAR = 2000
MAX_YEAR = 2100
MIN_SBERBANK_COLUMNS = 3

# Bank detection strings
RAIFFEISEN_BANK_NAME = 'Райффайзенбанк'
SBERBANK_CREDIT_CARD_TITLE = 'Выписка по счёту кредитной карты'
OZON_BANK_NAME = 'ОЗОН Банк'
OZON_STATEMENT_TITLE = 'Справка о движении средств'
ROSDORBANK_BANK_NAME = 'ПАО "РосДорБанк"'
ROSDORBANK_STATEMENT_TITLE = 'Выписка по счету'

# Raiffeisen column indices
RAIFFEISEN_NUM_COL = 0
RAIFFEISEN_DATE_COL = 1
RAIFFEISEN_DOC_COL = 2
RAIFFEISEN_INCOME_COL = 3
RAIFFEISEN_EXPENSE_COL = 4
RAIFFEISEN_DESCRIPTION_COL = 5

# Sberbank column indices
SBERBANK_DATE_COL = 0
SBERBANK_CATEGORY_COL = 1
SBERBANK_AMOUNT_COL = 2
SBERBANK_BALANCE_COL = 3

# Ozon column indices
OZON_DATE_COL = 0
OZON_DOCUMENT_COL = 1
OZON_DESCRIPTION_COL = 2
OZON_AMOUNT_COL = 3

OZON_PURCHASE_CATEGORY = 'Покупки Ozon'
OZON_REFUND_CATEGORY = 'Возвраты Ozon'
OZON_TIP_CATEGORY = 'Чаевые Ozon'

# RosDorBank table headers; their x positions locate the columns.
ROSDORBANK_NUMBER_HEADER = '№'
ROSDORBANK_DEBIT_HEADER = 'Списание'
ROSDORBANK_CREDIT_HEADER = 'Зачисление'
ROSDORBANK_TABLE_HEADERS = frozenset(
    {
        ROSDORBANK_NUMBER_HEADER,
        'Контрагент/Операция',
        ROSDORBANK_DEBIT_HEADER,
        ROSDORBANK_CREDIT_HEADER,
    },
)
ROSDORBANK_CLOSING_LABEL = 'Исходящий остаток:'
ROSDORBANK_TOTAL_LABELS = (
    'Входящий остаток:',
    'Обороты',
    ROSDORBANK_CLOSING_LABEL,
)
ROSDORBANK_MERCHANT_PREFIXES = ('PMP', '3DI2')
ROSDORBANK_MIN_MERCHANT_KEY_LETTERS = 4
ROSDORBANK_C2C_FALLBACK_DESCRIPTION = 'Перевод СБП'
# Lines at the same baseline differ by rounding only.
ROSDORBANK_SAME_LINE_TOLERANCE = 2.0


class BankStatementParseError(Exception):
    """Exception raised when parsing bank statement fails."""


def _dedup_transactions(
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate transactions within a single parsed statement.

    Transactions with the same non-empty ``source_ref`` are considered
    duplicates regardless of other fields. Transactions without a
    ``source_ref`` fall back to ``(date, amount, description)``.
    """
    seen_refs: set[str] = set()
    unique: list[dict[str, Any]] = []
    for position, t in enumerate(transactions):
        t['row_position'] = position
        ref = t.get('source_ref')
        if ref:
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            unique.append(t)
            continue
        unique.append(t)
    return unique


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseBankStatementParser(ABC):
    """Abstract base class for bank statement parsers."""

    def __init__(self, pdf_path: str | Path) -> None:
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            error_msg = f'PDF file not found: {pdf_path}'
            raise FileNotFoundError(error_msg)

    @abstractmethod
    def parse(self) -> StatementParseResult:
        """Parse PDF and return transactions and reconciliation data.

        Each transaction dict has keys: date (datetime), amount (Decimal),
        and description (str).
        """

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    def _read_tables(self, pages: str = 'all') -> list[Any]:
        """Read all tables from the PDF using camelot stream mode."""
        return cast(
            'list[Any]',
            camelot.read_pdf(  # type: ignore[attr-defined]
                str(self.pdf_path),
                flavor='stream',
                pages=pages,
                suppress_stdout=True,
            ),
        )

    def _extract_amount_from_column(self, text: str) -> Decimal | None:
        """Extract a positive Decimal amount from a column text cell.

        The caller is responsible for applying the correct sign
        (+ income / - expense).
        """
        if not text or text == 'nan':
            return None

        amount_pattern = r'[+-]?\s*(\d+(?:[\s\xa0]+\d+)*,\d{2})\s*₽'
        match = re.search(amount_pattern, text)
        if match:
            amount_str = (
                match.group(1)
                .replace('\xa0', '')
                .replace(' ', '')
                .replace(',', '.')
            )
            try:
                return Decimal(amount_str)
            except InvalidOperation:
                pass
        return None

    def _extract_date(self, text: str) -> datetime | None:
        """Extract a datetime from text supporting DD.MM.YYYY HH:MM.

        Also handles newline-separated date/time as found in Sberbank PDFs:
        e.g. '18.02.2026\n17:11'. Also supports DD.MM.YYYY format.
        """
        # Support both space and newline as separator between date and time
        datetime_pattern = r'\b(\d{2}\.\d{2}\.\d{4})[\s\n]+(\d{2}):(\d{2})\b'
        match = re.search(datetime_pattern, text)
        if match:
            try:
                full_str = f'{match.group(1)} {match.group(2)}:{match.group(3)}'
                parsed = datetime.strptime(full_str, '%d.%m.%Y %H:%M').replace(
                    tzinfo=timezone.get_current_timezone(),
                )
                if MIN_YEAR <= parsed.year <= MAX_YEAR:
                    return parsed
            except ValueError:
                pass

        date_pattern = r'\b(\d{2}\.\d{2}\.\d{4})\b'
        match = re.search(date_pattern, text)
        if match:
            try:
                parsed = datetime.strptime(match.group(1), '%d.%m.%Y').replace(
                    tzinfo=timezone.get_current_timezone(),
                )
                if MIN_YEAR <= parsed.year <= MAX_YEAR:
                    return parsed
            except ValueError:
                pass
        return None

    def _clean_description(self, description: str) -> str:
        """Clean and normalise transaction description."""
        if not description:
            return 'Операция'

        atm_match = re.match(
            r'^(Выдача наличных(?:\s+средств)?(?:\s+со счета)?'
            r'(?:\s+через банкомат)?)',
            description,
            re.IGNORECASE,
        )
        if atm_match:
            return 'Выдача наличных'

        cleaned = re.sub(r'\s+\d{2}\.\d{2}\.\d{2,4}', '', description)
        cleaned = re.sub(
            r'\s*\d+(?:\s?\d+)*(?:,\d{2})?\s*(?:руб\.?|₽)',
            '',
            cleaned,
        )
        cleaned = re.sub(
            r'\s*(?:ATM|терминал)\s*\d+',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r'\s*[,;]?\s*г\s+[^,]+(?:,\s*[^,]+)*$', '', cleaned)
        cleaned = cleaned.strip(' ,;.')

        if not cleaned:
            parts = description.split(',')
            if parts:
                return parts[0].strip()[:100]
            return description[:100]

        return cleaned

    def _extract_closing_balance(self, full_text: str) -> Decimal | None:
        """Извлечь конечный остаток из текста выписки.

        Args:
            full_text: Полный текст PDF-выписки, полученный через pdfminer.

        Returns:
            Конечный остаток как ``Decimal`` или ``None``, если не найден.
        """
        pattern = (
            r'(?:Исходящий остаток|Остаток на конец периода'
            r'|Остаток на конец|Конечный остаток|Closing balance)'
            r'[^\d\-]*([+-]?\s*\d[\d\s\xa0]*[,\.]\d{2})'
        )
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
                pass
        return None


# ---------------------------------------------------------------------------
# Generic Russian bank parser (original logic)
# ---------------------------------------------------------------------------


class _GenericBankParser(BaseBankStatementParser):
    """Generic parser for Russian bank statements."""

    def parse(self) -> StatementParseResult:
        """Разобрать PDF-выписку неизвестного банка.

        Returns:
            ``StatementParseResult`` со списком операций и конечным остатком
            (если удалось извлечь из текста).

        Raises:
            BankStatementParseError: При любой ошибке парсинга.
        """
        try:
            logger.info('bank_statement_parse_started', parser='generic')
            try:
                full_text = extract_text(str(self.pdf_path))
            except Exception:
                full_text = ''
            tables = self._read_tables()
            logger.info('bank_statement_tables_found', tables=len(tables))
            transactions: list[dict[str, Any]] = []

            for idx, table in enumerate(tables):
                logger.info(
                    'bank_statement_table_processing',
                    table=idx + 1,
                    tables=len(tables),
                )
                table_df = table.df
                if len(
                    table_df.columns,
                ) >= MIN_TABLE_COLUMNS and self._is_transaction_table(
                    table_df,
                ):
                    parsed = self._parse_table(table_df)
                    logger.info(
                        'bank_statement_table_extracted',
                        transactions=len(parsed),
                        table=idx + 1,
                    )
                    transactions.extend(parsed)

            transactions = [
                t for t in transactions if t['amount'] != Decimal(0)
            ]
            transactions = _dedup_transactions(transactions)
            closing_balance = self._extract_closing_balance(full_text)

            logger.info(
                'bank_statement_parse_completed',
                parser='generic',
                transactions=len(transactions),
                closing_balance=str(closing_balance),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('bank_statement_parse_failed')
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return StatementParseResult(
                transactions=transactions,
                closing_balance=closing_balance,
            )

    def _is_transaction_table(self, df: pd.DataFrame) -> bool:
        for _idx, row in df.iterrows():
            if len(row) > 0:
                first_col = str(row.iloc[0])
                if self._extract_transaction_number(first_col) is not None:
                    return True
        return False

    def _extract_transaction_number(self, text: str) -> int | None:
        match = re.match(r'^\s*(\d+)\s*$', text.strip())
        if match:
            return int(match.group(1))
        return None

    def _parse_table(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        transactions: list[dict[str, Any]] = []
        for row_idx, row in df.iterrows():
            try:
                first_col = str(row.iloc[0]) if len(row) > 0 else ''
                if not first_col or first_col == 'nan':
                    continue
                if self._extract_transaction_number(first_col) is None:
                    continue
                row_index = int(row_idx) if isinstance(row_idx, int) else 0
                trans = self._parse_transaction_row(row, df, row_index)
                if trans:
                    transactions.append(trans)
            except ValueError as e:
                logger.warning(
                    'bank_statement_row_parse_failed',
                    row=row_idx,
                    error=str(e),
                )
        return transactions

    def _parse_transaction_row(
        self,
        row: pd.Series,
        df: pd.DataFrame,
        index: int,
    ) -> dict[str, Any] | None:
        amount = self._extract_amount_from_row(row)
        if amount is None:
            return None

        description_col_idx = self._get_description_column_index(row)
        date = self._extract_date_from_context(df, index)
        if date is None:
            return None

        description = self._extract_description(
            row,
            df,
            index,
            description_col_idx,
        )
        description = self._clean_description(description)
        if not description:
            description = 'Операция'

        return {
            'date': date,
            'amount': amount,
            'description': description[:250],
            'source_ref': self._extract_source_ref(row),
        }

    def _extract_source_ref(self, row: pd.Series) -> str | None:
        """Return a stable per-bank operation id, or None if unavailable."""
        return None

    def _extract_amount_from_row(self, row: pd.Series) -> Decimal | None:
        for col_idx in range(2, len(row)):
            col_text = str(row.iloc[col_idx])
            extracted = self._extract_amount_from_column(col_text)
            if extracted is not None:
                if '+' in col_text:
                    return extracted
                if '-' in col_text:
                    return -extracted
                return extracted
        return None

    def _get_description_column_index(self, row: pd.Series) -> int:
        return 5 if len(row) >= MIN_STANDARD_COLUMNS else 2

    def _extract_date_from_context(
        self,
        df: pd.DataFrame,
        index: int,
    ) -> datetime | None:
        for i in range(index, max(0, index - 5), -1):
            check_row = df.iloc[i]
            for col_idx in range(min(2, len(check_row))):
                if len(check_row) > col_idx:
                    date = self._extract_date(str(check_row.iloc[col_idx]))
                    if date:
                        return date
        return None

    def _extract_description(
        self,
        row: pd.Series,
        df: pd.DataFrame,
        index: int,
        description_col_idx: int,
    ) -> str:
        parts: list[str] = []

        if len(row) > description_col_idx:
            desc_text = str(row.iloc[description_col_idx])
            if desc_text and desc_text != 'nan':
                desc_text = desc_text.strip()
                if desc_text:
                    parts.append(desc_text)

        for next_idx in range(index + 1, min(index + 10, len(df))):
            next_row = df.iloc[next_idx]
            if len(next_row) > 0:
                first_col = str(next_row.iloc[0])
                if self._extract_transaction_number(first_col) is not None:
                    break
            if len(next_row) > description_col_idx:
                desc_text = str(next_row.iloc[description_col_idx])
                if desc_text and desc_text != 'nan':
                    desc_text = desc_text.strip()
                    if desc_text and not re.match(
                        r'^(\d{5,}|\*\d{4}|Со счета:|На счет:)',
                        desc_text,
                    ):
                        parts.append(desc_text)

        return ' '.join(parts).strip()


# ---------------------------------------------------------------------------
# Raiffeisen parser
# ---------------------------------------------------------------------------


class _RaiffeisenBankParser(_GenericBankParser):
    """Parser for Raiffeisen bank statements.

    Columns: [0]=№ | [1]=Дата | [2]=Номер документа |
    [3]=Поступления | [4]=Расходы | [5]=Детали операции |
    [6]=Номер карты
    """

    def parse(self) -> StatementParseResult:
        """Разобрать PDF-выписку Райффайзенбанка.

        Returns:
            ``StatementParseResult`` со списком операций и конечным остатком.
        """
        logger.info('bank_statement_parse_started', parser='raiffeisen')
        return super().parse()

    def _extract_amount_from_row(self, row: pd.Series) -> Decimal | None:
        """Read income from col[3] and expense from col[4]."""
        if len(row) > RAIFFEISEN_INCOME_COL:
            income_text = str(row.iloc[RAIFFEISEN_INCOME_COL])
            amount = self._extract_amount_from_column(income_text)
            if amount is not None:
                return amount  # positive → Income

        if len(row) > RAIFFEISEN_EXPENSE_COL:
            expense_text = str(row.iloc[RAIFFEISEN_EXPENSE_COL])
            amount = self._extract_amount_from_column(expense_text)
            if amount is not None:
                return -amount  # negative → Expense

        return None

    def _get_description_column_index(self, row: pd.Series) -> int:
        return RAIFFEISEN_DESCRIPTION_COL

    def _extract_source_ref(self, row: pd.Series) -> str | None:
        """Return Raiffeisen document number from col[2] if numeric."""
        if len(row) <= RAIFFEISEN_DOC_COL:
            return None
        text = str(row.iloc[RAIFFEISEN_DOC_COL]).strip()
        if not text or text == 'nan':
            return None
        match = re.search(r'(\d{3,})', text)
        if match:
            return match.group(1)
        return None


# ---------------------------------------------------------------------------
# Sberbank credit card parser
# ---------------------------------------------------------------------------


class _SberbankParser(BaseBankStatementParser):
    """Parser for Sberbank credit card statements.

    Two-row-per-transaction structure:
    Row A: date+time | category | amount | balance
    Row B: date/authcode | description text | (empty) | (empty)

    Columns: [0]=Дата | [1]=Категория | [2]=Сумма | [3]=Остаток
    """

    def parse(self) -> StatementParseResult:
        """Разобрать PDF-выписку Сбербанка (кредитная карта).

        Returns:
            ``StatementParseResult`` со списком операций и конечным остатком.

        Raises:
            BankStatementParseError: При любой ошибке парсинга.
        """
        try:
            logger.info('bank_statement_parse_started', parser='sberbank')
            try:
                full_text = extract_text(str(self.pdf_path))
            except Exception:
                full_text = ''
            tables = self._read_tables()
            logger.info('bank_statement_tables_found', tables=len(tables))
            transactions: list[dict[str, Any]] = []

            for idx, table in enumerate(tables):
                logger.info(
                    'bank_statement_table_processing',
                    table=idx + 1,
                    tables=len(tables),
                )
                table_df = table.df
                if len(
                    table_df.columns,
                ) >= MIN_SBERBANK_COLUMNS and self._is_transaction_table(
                    table_df,
                ):
                    parsed = self._parse_table(table_df)
                    logger.info(
                        'bank_statement_table_extracted',
                        transactions=len(parsed),
                        table=idx + 1,
                    )
                    transactions.extend(parsed)

            transactions = [
                t for t in transactions if t['amount'] != Decimal(0)
            ]
            transactions = _dedup_transactions(transactions)
            closing_balance = self._extract_closing_balance(full_text)

            logger.info(
                'bank_statement_parse_completed',
                parser='sberbank',
                transactions=len(transactions),
                closing_balance=str(closing_balance),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('bank_statement_parse_failed')
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return StatementParseResult(
                transactions=transactions,
                closing_balance=closing_balance,
            )

    def _is_transaction_table(self, df: pd.DataFrame) -> bool:
        """Detect Sberbank transaction table by column header keywords."""
        for _, row in df.iterrows():
            row_text = ' '.join(str(v) for v in row.to_numpy())
            if any(
                keyword in row_text
                for keyword in (
                    'ДАТА ОПЕРАЦИИ',
                    'КАТЕГОРИЯ',
                    'Дата операции',
                    'Категория',
                    'СУММА',
                    'ОСТАТОК',
                )
            ):
                return True
        # Fallback: if col[0] contains a datetime pattern,
        # treat as transaction table
        for _, row in df.iterrows():
            cell = str(row.iloc[0]) if len(row) > 0 else ''
            if self._extract_date(cell) is not None:
                return True
        return False

    def _find_data_start_row(self, df: pd.DataFrame) -> int:
        """Return index of first row where col[0] contains a valid date."""
        for i in range(len(df)):
            cell = (
                str(df.iloc[i, SBERBANK_DATE_COL])
                if len(df.columns) > 0
                else ''
            )
            if self._extract_date(cell) is not None:
                return i
        return 0

    def _parse_table(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Parse Sberbank table with paired-row (A+B) structure.

        Supports two layouts:
        - 4-column: col[0]=date, col[1]=category, col[2]=amount,
          col[3]=balance
        - 3-column: col[0]=date, col[1]='category\\namount',
          col[2]=balance (happens when PDF columns are merged, e.g. on
          last page)
        """
        transactions: list[dict[str, Any]] = []
        num_cols = len(df.columns)
        merged_col = num_cols == MIN_SBERBANK_COLUMNS
        data_start = self._find_data_start_row(df)
        logger.debug(
            'bank_statement_table_layout',
            data_start=data_start,
            rows=len(df),
            columns=num_cols,
            merged=merged_col,
        )
        i = data_start

        while i < len(df):
            result = self._parse_sberbank_row_pair(
                df,
                i,
                merged_col,
                transactions,
            )
            i = result

        return transactions

    def _parse_sberbank_row_pair(
        self,
        df: pd.DataFrame,
        i: int,
        merged_col: bool,
        transactions: list[dict[str, Any]],
    ) -> int:
        """Parse a pair of Sberbank rows and return next index.

        Handles the edge case where row A is the last row in the table
        (no row B available) by treating the transaction as single-row.
        """
        row_a = df.iloc[i]
        row_b = df.iloc[i + 1] if i + 1 < len(df) else None

        date = self._extract_date(
            str(row_a.iloc[SBERBANK_DATE_COL])
            if len(row_a) > SBERBANK_DATE_COL
            else '',
        )
        if date is None:
            return i + 1

        if merged_col:
            return self._parse_merged_layout(
                row_a,
                row_b,
                i,
                date,
                transactions,
            )
        return self._parse_standard_layout(row_a, row_b, i, date, transactions)

    def _extract_authcode(self, row: pd.Series | None) -> str | None:
        """Extract Sberbank authorization code from a row B-like cell.

        Row B's date column may have one of two shapes:
        * ``'DD.MM.YYYY / 869838'`` — older layouts.
        * ``'DD.MM.YYYY\\n869838\\n<description>'`` — the merged 3-column
          layout used on the last page of multi-page statements.
        The 3-7 digit number after the date uniquely identifies the
        transaction within the account.
        """
        if row is None or len(row) <= SBERBANK_DATE_COL:
            return None
        text = str(row.iloc[SBERBANK_DATE_COL])
        if not text or text == 'nan':
            return None
        match = re.search(r'\d{2}\.\d{2}\.\d{4}[\s/\n]+(\d{3,7})\b', text)
        if match:
            return match.group(1)
        return None

    def _parse_merged_layout(
        self,
        row_a: pd.Series,
        row_b: pd.Series | None,
        i: int,
        date: datetime,
        transactions: list[dict[str, Any]],
    ) -> int:
        """Parse 3-column merged layout used on the last PDF page.

        The merged layout packs row A into:
        * col[0]: ``'DD.MM.YYYY\\nHH:MM\\nCategory'``
        * col[1]: amount, e.g. ``'2 958,00'`` (no ₽ sign)
        * col[2]: balance

        Row B (continuation) carries the authcode in col[0] as
        ``'DD.MM.YYYY\\nAUTHCODE\\nDescription'``.
        """
        col0_text = (
            str(row_a.iloc[SBERBANK_DATE_COL]).strip()
            if len(row_a) > SBERBANK_DATE_COL
            else ''
        )
        if col0_text == 'nan':
            col0_text = ''

        category = self._extract_category_from_merged_col0(col0_text)
        amount_text = (
            str(row_a.iloc[SBERBANK_CATEGORY_COL]).strip()
            if len(row_a) > SBERBANK_CATEGORY_COL
            else ''
        )
        if amount_text == 'nan':
            amount_text = ''

        if row_b is None:
            self._add_transaction_if_valid(
                transactions,
                date,
                amount_text,
                category,
                None,
            )
            return i + 1

        source_ref = self._extract_authcode(row_b)
        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
                    'source_ref': source_ref,
                },
            )
        return i + 2

    def _extract_category_from_merged_col0(self, text: str) -> str:
        """Return the category line from a merged col[0] cell.

        Strips the leading ``DD.MM.YYYY`` date and ``HH:MM`` time lines and
        returns whatever follows them. Returns '' if no category line is
        present.
        """
        if not text:
            return ''
        cleaned = re.sub(r'^\s*\d{2}\.\d{2}\.\d{4}\s*\n?', '', text)
        cleaned = re.sub(r'^\s*\d{2}:\d{2}\s*\n?', '', cleaned)
        return cleaned.strip()

    def _parse_standard_layout(
        self,
        row_a: pd.Series,
        row_b: pd.Series | None,
        i: int,
        date: datetime,
        transactions: list[dict[str, Any]],
    ) -> int:
        """Parse 4-column standard layout.

        When row_b is None (row_a is the last row in the table) the
        transaction is treated as single-row: still emit it, just without
        the row B continuation.
        """
        if row_b is not None:
            row_b_amount = (
                str(row_b.iloc[SBERBANK_AMOUNT_COL])
                if len(row_b) > SBERBANK_AMOUNT_COL
                else ''
            )
            if row_b_amount not in ('', 'nan'):
                return i + 1

        category = (
            str(row_a.iloc[SBERBANK_CATEGORY_COL]).strip()
            if len(row_a) > SBERBANK_CATEGORY_COL
            else ''
        )
        if category == 'nan':
            category = ''

        amount_text = (
            str(row_a.iloc[SBERBANK_AMOUNT_COL])
            if len(row_a) > SBERBANK_AMOUNT_COL
            else ''
        )
        source_ref = self._extract_authcode(row_b)
        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
                    'source_ref': source_ref,
                },
            )
        return i + 2 if row_b is not None else i + 1

    def _add_transaction_if_valid(
        self,
        transactions: list[dict[str, Any]],
        date: datetime,
        amount_text: str,
        category: str,
        source_ref: str | None,
    ) -> None:
        """Add transaction to list if amount is valid and non-zero."""
        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
                    'source_ref': source_ref,
                },
            )

    def _extract_sberbank_amount(self, text: str) -> Decimal | None:
        """Extract signed amount: '+' → positive, else negative.

        Sberbank statements use format like '500,00' or '+50 546,00'
        (no ₽ symbol).
        """
        if not text or text == 'nan':
            return None

        stripped = text.strip()

        # First try the general extractor (handles amounts with ₽)
        base = self._extract_amount_from_column(stripped)

        # Fallback: Sberbank format — digits with non-breaking spaces
        # (\xa0) or regular spaces as thousands separators,
        # comma as decimal separator, e.g. '1\xa0000,00'
        if base is None:
            # Pattern: optional sign, digits (with optional whitespace
            # thousands separator), comma, 2 digits
            amount_pattern = r'[+-]?\s*(\d+(?:[\s\xa0]\d+)*,\d{2})'
            match = re.search(amount_pattern, stripped)
            if match:
                # Remove both regular spaces and non-breaking spaces
                # before converting
                amount_str = (
                    match.group(1)
                    .replace('\xa0', '')
                    .replace(' ', '')
                    .replace(',', '.')
                )
                try:
                    base = Decimal(amount_str)
                except InvalidOperation:
                    return None

        if base is None:
            return None

        if stripped.startswith('+'):
            return base  # income
        return -base  # expense


# ---------------------------------------------------------------------------
# Ozon Bank parser
# ---------------------------------------------------------------------------


class _OzonBankParser(BaseBankStatementParser):
    """Parser for Ozon Bank cash-flow statements.

    Columns: [0]=Дата операции | [1]=Документ |
    [2]=Назначение платежа | [3]=Российские рубли | [4]=Валюта
    """

    _operation_start_pattern = re.compile(
        r'^\s*\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}\b',
    )

    def parse(self) -> StatementParseResult:
        """Parse purchases, refunds, and tips from an Ozon statement."""
        try:
            logger.info('bank_statement_parse_started', parser='ozon')
            tables = self._read_tables()
            transactions: list[dict[str, Any]] = []
            operation_rows = 0

            for table in tables:
                parsed, table_operation_rows = self._parse_table(table.df)
                transactions.extend(parsed)
                operation_rows += table_operation_rows

            if operation_rows == 0:
                error_msg = (
                    'В выписке Ozon не найдены строки банковских операций'
                )
                raise BankStatementParseError(error_msg)

            transactions = _dedup_transactions(transactions)
            logger.info(
                'bank_statement_parse_completed',
                parser='ozon',
                transactions=len(transactions),
                operations=operation_rows,
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('bank_statement_parse_failed', parser='ozon')
            error_msg = f'Не удалось обработать PDF Ozon: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            # Transfers are intentionally excluded, so closing-balance
            # reconciliation would report an expected false discrepancy.
            return StatementParseResult(transactions=transactions)

    def _parse_table(
        self,
        df: pd.DataFrame,
    ) -> tuple[list[dict[str, Any]], int]:
        transactions: list[dict[str, Any]] = []
        operation_rows = 0
        index = 0

        while index < len(df):
            row = df.iloc[index]
            date_text = self._cell(row, OZON_DATE_COL)
            if not self._operation_start_pattern.match(date_text):
                index += 1
                continue

            operation_rows += 1
            parts = [row]
            next_index = index + 1
            while next_index < len(df):
                next_row = df.iloc[next_index]
                if self._operation_start_pattern.match(
                    self._cell(next_row, OZON_DATE_COL),
                ):
                    break
                parts.append(next_row)
                next_index += 1

            transaction = self._parse_operation(parts)
            if transaction is not None:
                transactions.append(transaction)
            index = next_index

        return transactions, operation_rows

    def _parse_operation(
        self,
        rows: list[pd.Series],
    ) -> dict[str, Any] | None:
        date_text = ' '.join(self._cell(row, OZON_DATE_COL) for row in rows)
        trans_date = self._extract_ozon_date(date_text)
        source_ref = re.sub(
            r'\s+',
            '',
            self._joined_column(rows, OZON_DOCUMENT_COL),
        )
        description = self._joined_column(rows, OZON_DESCRIPTION_COL)
        amount_text = self._joined_column(rows, OZON_AMOUNT_COL)

        if trans_date is None or not source_ref or not amount_text:
            error_msg = 'Не удалось разобрать строку операции Ozon'
            raise BankStatementParseError(error_msg)

        category = self._category_for_description(description)
        if category is None:
            logger.warning(
                'bank_statement_ozon_operation_skipped',
                source_ref=source_ref,
            )
            return None

        amount = self._extract_ozon_amount(amount_text)
        if amount is None or amount == Decimal(0):
            error_msg = f'Не удалось разобрать сумму операции Ozon {source_ref}'
            raise BankStatementParseError(error_msg)

        return {
            'date': trans_date,
            'amount': amount,
            'description': category,
            'category_name': category,
            'source_ref': source_ref,
            'source': 'ozon',
        }

    def _cell(self, row: pd.Series, index: int) -> str:
        if len(row) <= index:
            return ''
        value = str(row.iloc[index]).strip()
        return '' if value == 'nan' else value

    def _joined_column(self, rows: list[pd.Series], index: int) -> str:
        return re.sub(
            r'\s+',
            ' ',
            ' '.join(self._cell(row, index) for row in rows),
        ).strip()

    def _extract_ozon_date(self, text: str) -> datetime | None:
        match = re.search(
            r'\b(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2})\b',
            text,
        )
        if match is None:
            return None
        try:
            return datetime.strptime(
                f'{match.group(1)} {match.group(2)}',
                '%d.%m.%Y %H:%M:%S',
            ).replace(tzinfo=timezone.get_current_timezone())
        except ValueError:
            return None

    def _extract_ozon_amount(self, text: str) -> Decimal | None:
        match = re.search(
            r'([+-])\s*(\d+(?:[\s\xa0]+\d+)*[\.,]\d{2})\s*₽',
            text,
        )
        if match is None:
            return None
        raw = (
            match.group(2)
            .replace('\xa0', '')
            .replace(' ', '')
            .replace(',', '.')
        )
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return None
        return amount if match.group(1) == '+' else -amount

    def _category_for_description(self, description: str) -> str | None:
        if description.startswith('Возврат оплаты за товары/услуги'):
            return OZON_REFUND_CATEGORY
        if description.startswith('Оплата товаров/услуг на Платформе Ozon'):
            return OZON_PURCHASE_CATEGORY
        if description.startswith('Чаевые по заказу'):
            return OZON_TIP_CATEGORY
        return None


class RosDorBankRowKind(StrEnum):
    """Вид строки выписки РосДорБанка."""

    CARD = 'card'
    CANCEL = 'cancel'
    OWN_C2C = 'own_c2c'
    C2C = 'c2c'
    C2B = 'c2b'
    UNKNOWN = 'unknown'


def rosdorbank_merchant_key(text: str) -> str:
    """Ключ продавца: имя без префиксов, номеров терминалов и пунктуации."""
    prefixes = '|'.join(ROSDORBANK_MERCHANT_PREFIXES)
    name = re.sub(rf'^(?:{prefixes})\s+', '', text.strip())
    letters = ''.join(
        char for char in re.split(r'\d', name, maxsplit=1)[0] if char.isalpha()
    )
    if len(letters) < ROSDORBANK_MIN_MERCHANT_KEY_LETTERS:
        return ''.join(char for char in name if char.isalnum()).upper()
    return letters.upper()


@dataclass(frozen=True)
class _PdfLine:
    page: int
    top: float
    x0: float
    x1: float
    text: str


@dataclass
class _RosDorBankRow:
    date: date_type
    lines: list[str] = field(default_factory=list)
    number: str | None = None
    amount: Decimal | None = None
    is_credit: bool = False


class _RosDorBankParser(BaseBankStatementParser):
    """Parser for RosDorBank account statements.

    camelot splits this layout into different columns on every page, so
    rows are read from pdfminer text lines and placed by x position.
    A row starts at its ``БИК:`` line; the day date comes from the block
    header above it.
    """

    _header_pattern = re.compile(
        r'Выписка по счету (\d{20}) с (\d{2}\.\d{2}\.\d{4}) '
        r'по (\d{2}\.\d{2}\.\d{4})',
    )
    _date_pattern = re.compile(r'\d{2}\.\d{2}\.\d{4}')
    _amount_pattern = re.compile(r'\d{1,3}(?: \d{3})*\.\d{2}')
    _number_pattern = re.compile(r'\d+')
    _operation_pattern = re.compile(
        r'Отмена\. |Списание суммы операции|СБП- ',
    )
    _phone_pattern = re.compile(r'\+?\d[\d\s()\-]{9,}\d')

    def parse(self) -> StatementParseResult:
        """Parse every row; none of them is final until the user marks it."""
        try:
            logger.info('bank_statement_parse_started', parser='rosdorbank')
            result = self._parse_lines(self._read_lines())
            result.transactions = _dedup_transactions(result.transactions)
            logger.info(
                'bank_statement_parse_completed',
                parser='rosdorbank',
                transactions=len(result.transactions),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('bank_statement_parse_failed', parser='rosdorbank')
            error_msg = f'Не удалось обработать PDF РосДорБанка: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return result

    def _read_lines(self) -> list[_PdfLine]:
        lines: list[_PdfLine] = []
        for page_index, page in enumerate(extract_pages(str(self.pdf_path))):
            for element in page:
                if not isinstance(element, LTTextContainer):
                    continue
                for line in element:
                    text = line.get_text().strip()
                    if isinstance(line, LTTextLine) and text:
                        lines.append(
                            _PdfLine(
                                page=page_index,
                                top=-line.y1,
                                x0=line.x0,
                                x1=line.x1,
                                text=text,
                            ),
                        )
        lines.sort(key=lambda line: (line.page, line.top, line.x0))
        return lines

    def _parse_lines(self, lines: list[_PdfLine]) -> StatementParseResult:
        header = next(
            (
                match
                for line in lines
                if (match := self._header_pattern.search(line.text))
            ),
            None,
        )
        columns: dict[str, _PdfLine] = {}
        for line in lines:
            if line.text in ROSDORBANK_TABLE_HEADERS:
                columns.setdefault(line.text, line)
        if header is None or len(columns) < len(ROSDORBANK_TABLE_HEADERS):
            error_msg = 'В выписке РосДорБанка не найдены шапка или таблица'
            raise BankStatementParseError(error_msg)

        table_lines, closing_balance = self._split_totals(lines, columns)
        rows = self._group_rows(table_lines, columns)
        return StatementParseResult(
            transactions=[self._build_transaction(row) for row in rows],
            closing_balance=closing_balance,
            closing_balance_date=self._parse_day(header.group(3)),
            account_number=header.group(1),
            period_start=self._parse_day(header.group(2)),
        )

    def _split_totals(
        self,
        lines: list[_PdfLine],
        columns: dict[str, _PdfLine],
    ) -> tuple[list[_PdfLine], Decimal | None]:
        """Drop amounts of balance/turnover lines, keep the closing one."""
        totals: dict[int, list[tuple[float, str]]] = {}
        for line in lines:
            if line.text.startswith(ROSDORBANK_TOTAL_LABELS):
                totals.setdefault(line.page, []).append((line.top, line.text))

        table_lines: list[_PdfLine] = []
        closing_balance: Decimal | None = None
        for line in lines:
            label = (
                self._total_label(line, totals)
                if self._cell_kind(line, columns) == 'amount'
                else None
            )
            if label is None:
                table_lines.append(line)
            elif label.startswith(ROSDORBANK_CLOSING_LABEL):
                closing_balance = Decimal(line.text.replace(' ', ''))
        return table_lines, closing_balance

    def _group_rows(
        self,
        lines: list[_PdfLine],
        columns: dict[str, _PdfLine],
    ) -> list[_RosDorBankRow]:
        rows: list[_RosDorBankRow] = []
        current: _RosDorBankRow | None = None
        # A № or amount on the baseline of the next БИК line sorts before
        # it, so it opens that row ahead of time.
        upcoming: _RosDorBankRow | None = None
        day: date_type | None = None
        for line in lines:
            if line.text in ROSDORBANK_TABLE_HEADERS:
                continue
            if self._date_pattern.fullmatch(line.text):
                day = self._parse_day(line.text)
                continue
            cell = self._cell_kind(line, columns)
            if cell is not None:
                row = current
                if (
                    row is None
                    or (row.amount if cell == 'amount' else row.number)
                    is not None
                ):
                    upcoming = upcoming or self._open_row(rows, day)
                    row = upcoming
                self._fill_cell(row, line, cell, columns)
                continue
            if line.text.startswith(ROSDORBANK_TOTAL_LABELS):
                current = None
                continue
            if line.text.startswith('БИК:'):
                current = upcoming or self._open_row(rows, day)
                upcoming = None
            if current is not None:
                current.lines.append(line.text)
        return rows

    def _cell_kind(
        self,
        line: _PdfLine,
        columns: dict[str, _PdfLine],
    ) -> str | None:
        if line.x1 > columns[ROSDORBANK_DEBIT_HEADER].x0:
            return (
                'amount' if self._amount_pattern.fullmatch(line.text) else None
            )
        if line.x0 < columns[ROSDORBANK_NUMBER_HEADER].x1:
            return (
                'number' if self._number_pattern.fullmatch(line.text) else None
            )
        return None

    @staticmethod
    def _total_label(
        line: _PdfLine,
        totals: dict[int, list[tuple[float, str]]],
    ) -> str | None:
        return next(
            (
                text
                for top, text in totals.get(line.page, [])
                if abs(top - line.top) <= ROSDORBANK_SAME_LINE_TOLERANCE
            ),
            None,
        )

    @staticmethod
    def _fill_cell(
        row: _RosDorBankRow,
        line: _PdfLine,
        cell: str,
        columns: dict[str, _PdfLine],
    ) -> None:
        if cell == 'amount':
            row.amount = Decimal(line.text.replace(' ', ''))
            row.is_credit = line.x1 > columns[ROSDORBANK_CREDIT_HEADER].x0
        else:
            row.number = line.text

    @staticmethod
    def _parse_day(text: str) -> date_type:
        return (
            datetime.strptime(text, '%d.%m.%Y')
            .replace(tzinfo=timezone.get_current_timezone())
            .date()
        )

    @staticmethod
    def _open_row(
        rows: list[_RosDorBankRow],
        day: date_type | None,
    ) -> _RosDorBankRow:
        if day is None:
            error_msg = 'Строка операции до даты дня в выписке'
            raise BankStatementParseError(error_msg)
        row = _RosDorBankRow(date=day)
        rows.append(row)
        return row

    def _build_transaction(self, row: _RosDorBankRow) -> dict[str, Any]:
        if row.number is None or row.amount is None or not row.lines:
            error_msg = 'Не удалось разобрать строку операции РосДорБанка'
            raise BankStatementParseError(error_msg)
        bik_line, *body_lines = row.lines
        account = re.search(r'р/с: (\d{20})', bik_line)
        body = ' '.join(body_lines)
        marker = self._operation_pattern.search(body)
        if marker is not None:
            party, operation = body[: marker.start()], body[marker.start() :]
        else:
            # shortcut: an address wrapped from the ИНН line stays in the
            # description; seen only in SBP rows so far, split if it shows up.
            party = body_lines[0] if body_lines else ''
            operation = ' '.join(body_lines[1:])
        kind, description, merchant_key = self._classify(party, operation)
        return {
            'date': datetime.combine(
                row.date,
                datetime.min.time(),
                tzinfo=timezone.get_current_timezone(),
            ),
            'amount': row.amount if row.is_credit else -row.amount,
            'description': description,
            'source_ref': f'{row.number}-{row.date:%d.%m.%Y}',
            'source': 'rosdorbank',
            'kind': kind,
            'merchant_key': merchant_key,
            'counterparty_account': account.group(1) if account else None,
        }

    def _classify(
        self,
        party: str,
        operation: str,
    ) -> tuple[RosDorBankRowKind, str, str | None]:
        owner = re.search(r'Владелец устройства:\s*(.+)$', operation)
        if owner is not None:
            device_owner = owner.group(1).strip()
            kind = (
                RosDorBankRowKind.CANCEL
                if operation.startswith('Отмена.')
                else RosDorBankRowKind.CARD
            )
            return kind, device_owner, rosdorbank_merchant_key(device_owner)

        if re.match(r'СБП- C2c\.', operation, re.IGNORECASE):
            payer = re.search(r'тел c:\s*(\+\d+)', operation)
            payee = re.search(r'тел C:\s*(\+\d+)', operation)
            is_own = (
                payer is not None
                and payee is not None
                and payer.group(1) == payee.group(1)
            )
            name = re.search(r', c: ([^,]+),', operation)
            description = (
                name.group(1).strip()
                if name
                else re.sub(r'^ИНН:\s*\d+\s*', '', party).split('//')[0].strip()
            ) or ROSDORBANK_C2C_FALLBACK_DESCRIPTION
            kind = (
                RosDorBankRowKind.OWN_C2C if is_own else RosDorBankRowKind.C2C
            )
            return kind, description, None

        c2b = re.match(
            r'СБП- C2b\..*?ТСП: "(.*?)"(?: Назначение: "(.*?)")?',
            operation,
        )
        if c2b is not None:
            merchant = c2b.group(1)
            purpose = self._strip_phones(c2b.group(2) or '')
            description = f'{merchant} — {purpose}' if purpose else merchant
            return (
                RosDorBankRowKind.C2B,
                description,
                rosdorbank_merchant_key(merchant),
            )

        return RosDorBankRowKind.UNKNOWN, self._strip_phones(operation), None

    def _strip_phones(self, text: str) -> str:
        return re.sub(r'\s+', ' ', self._phone_pattern.sub('', text)).strip(
            ' :',
        )


# ---------------------------------------------------------------------------
# Detection + factory
# ---------------------------------------------------------------------------


def _extract_pdf_text_for_detection(pdf_path: Path) -> str:
    """Extract raw text from the first page of a PDF for bank detection."""
    return extract_text(str(pdf_path), page_numbers=[0], maxpages=1)


def _create_parser(pdf_path: Path) -> BaseBankStatementParser:
    """Auto-detect bank from PDF content and return matching parser."""
    try:
        text = _extract_pdf_text_for_detection(pdf_path)
    except (OSError, ValueError, PDFSyntaxError) as e:
        logger.warning(
            'bank_statement_detection_text_unavailable',
            error=str(e),
        )
        text = ''

    bank_markers: tuple[
        tuple[tuple[str, ...], str, type[BaseBankStatementParser]],
        ...,
    ] = (
        ((RAIFFEISEN_BANK_NAME,), 'raiffeisen', _RaiffeisenBankParser),
        ((SBERBANK_CREDIT_CARD_TITLE,), 'sberbank', _SberbankParser),
        ((OZON_BANK_NAME, OZON_STATEMENT_TITLE), 'ozon', _OzonBankParser),
        (
            (ROSDORBANK_BANK_NAME, ROSDORBANK_STATEMENT_TITLE),
            'rosdorbank',
            _RosDorBankParser,
        ),
    )
    for markers, bank, parser_class in bank_markers:
        if all(marker in text for marker in markers):
            logger.info('bank_statement_bank_detected', bank=bank)
            return parser_class(pdf_path)

    # Fallback: column-header-based detection
    if 'Поступления' in text and '№ П/П' in text:
        logger.info(
            'bank_statement_bank_detected',
            bank='raiffeisen',
            via='column_headers',
        )
        return _RaiffeisenBankParser(pdf_path)

    if 'КАТЕГОРИЯ' in text and 'ОСТАТОК СРЕДСТВ' in text:
        logger.info(
            'bank_statement_bank_detected',
            bank='sberbank',
            via='column_headers',
        )
        return _SberbankParser(pdf_path)

    logger.info('bank_statement_bank_unknown')
    return _GenericBankParser(pdf_path)


# ---------------------------------------------------------------------------
# Public facade — preserves the original BankStatementParser API
# ---------------------------------------------------------------------------


class BankStatementParser:
    """Public facade that auto-detects bank and delegates to parser.

    The API is identical to the original BankStatementParser so that
    tasks.py and all existing tests require no changes.

    Attribute access is transparently proxied to the underlying delegate,
    so existing tests that call private helper methods (e.g. _extract_date)
    on a BankStatementParser instance continue to work without modification.
    """

    def __init__(self, pdf_path: str | Path) -> None:
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            error_msg = f'PDF file not found: {pdf_path}'
            raise FileNotFoundError(error_msg)
        self._delegate = _create_parser(self.pdf_path)

    def parse(self) -> StatementParseResult:
        """Разобрать PDF и вернуть результат парсинга.

        Returns:
            ``StatementParseResult`` с операциями и конечным остатком.
        """
        return self._delegate.parse()

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the delegate parser."""
        return getattr(self._delegate, name)


def _get_or_create_category(
    user: User,
    name: str,
    type_value: str,
) -> Category:
    category, _ = Category.objects.get_or_create(
        user=user,
        name=name[:250],
        type=type_value,
    )
    return category
