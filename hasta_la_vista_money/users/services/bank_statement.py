"""Service for parsing bank statements from PDF files.

Supports multiple bank formats with auto-detection:
- Raiffeisen (Райффайзенбанк)
- Sberbank credit card (Выписка по счёту кредитной карты)
- Generic Russian bank format (fallback)
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

import camelot
from django.db import transaction
from django.utils import timezone
from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import pandas as pd

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User

logger = logging.getLogger(__name__)

# General parsing constants
MIN_TABLE_COLUMNS = 5
MIN_STANDARD_COLUMNS = 7
MIN_YEAR = 2000
MAX_YEAR = 2100
MIN_SBERBANK_COLUMNS = 3

# Bank detection strings
RAIFFEISEN_BANK_NAME = 'Райффайзенбанк'
SBERBANK_CREDIT_CARD_TITLE = 'Выписка по счёту кредитной карты'

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


class BankStatementParseError(Exception):
    """Exception raised when parsing bank statement fails."""


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
    def parse(self) -> list[dict[str, Any]]:
        """Parse PDF and return list of transaction dicts.

        Each dict has keys: date (datetime), amount (Decimal),
        description (str).
        """

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    def _read_tables(self, pages: str = 'all') -> list[Any]:
        """Read all tables from the PDF using camelot stream mode."""
        return camelot.read_pdf(  # type: ignore[no-any-return]
            str(self.pdf_path),
            flavor='stream',
            pages=pages,
            suppress_stdout=True,
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


# ---------------------------------------------------------------------------
# Generic Russian bank parser (original logic)
# ---------------------------------------------------------------------------


class _GenericBankParser(BaseBankStatementParser):
    """Generic parser for Russian bank statements."""

    def parse(self) -> list[dict[str, Any]]:
        try:
            logger.info('Starting PDF parsing (generic): %s', self.pdf_path)
            tables = self._read_tables()
            logger.info('Found %d tables in PDF', len(tables))
            transactions: list[dict[str, Any]] = []

            for idx, table in enumerate(tables):
                logger.info('Processing table %d/%d', idx + 1, len(tables))
                table_df = table.df
                if len(
                    table_df.columns,
                ) >= MIN_TABLE_COLUMNS and self._is_transaction_table(
                    table_df,
                ):
                    parsed = self._parse_table(table_df)
                    logger.info(
                        'Extracted %d transactions from table %d',
                        len(parsed),
                        idx + 1,
                    )
                    transactions.extend(parsed)

            # Filter zero-amount transactions
            transactions = [
                t for t in transactions if t['amount'] != Decimal(0)
            ]

            # Remove duplicates based on (date, amount, description)
            seen: set[tuple[str, str, str]] = set()
            unique_transactions: list[dict[str, Any]] = []
            for t in transactions:
                key = (str(t['date']), str(t['amount']), t['description'])
                if key not in seen:
                    seen.add(key)
                    unique_transactions.append(t)
            transactions = unique_transactions

            logger.info(
                'Parsing complete. Total transactions: %d (after dedup)',
                len(transactions),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('Failed to parse PDF: %s', self.pdf_path)
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return transactions

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
        transactions = []
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
                logger.warning('Failed to parse row %s: %s', row_idx, e)
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
        }

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

    def parse(self) -> list[dict[str, Any]]:
        logger.info('Starting PDF parsing (Raiffeisen): %s', self.pdf_path)
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

    def parse(self) -> list[dict[str, Any]]:
        try:
            logger.info('Starting PDF parsing (Sberbank): %s', self.pdf_path)
            tables = self._read_tables()
            logger.info('Found %d tables in PDF', len(tables))
            transactions: list[dict[str, Any]] = []

            for idx, table in enumerate(tables):
                logger.info('Processing table %d/%d', idx + 1, len(tables))
                table_df = table.df
                if len(
                    table_df.columns,
                ) >= MIN_SBERBANK_COLUMNS and self._is_transaction_table(
                    table_df,
                ):
                    parsed = self._parse_table(table_df)
                    logger.info(
                        'Extracted %d transactions from table %d',
                        len(parsed),
                        idx + 1,
                    )
                    transactions.extend(parsed)

            # Filter zero-amount transactions
            transactions = [
                t for t in transactions if t['amount'] != Decimal(0)
            ]

            # Remove duplicates based on (date, amount, description)
            seen: set[tuple[str, str, str]] = set()
            unique_transactions: list[dict[str, Any]] = []
            for t in transactions:
                key = (str(t['date']), str(t['amount']), t['description'])
                if key not in seen:
                    seen.add(key)
                    unique_transactions.append(t)
            transactions = unique_transactions

            logger.info(
                'Parsing complete. Total transactions: %d (after dedup)',
                len(transactions),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('Failed to parse PDF: %s', self.pdf_path)
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return transactions

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
        transactions = []
        num_cols = len(df.columns)
        merged_col = num_cols == MIN_SBERBANK_COLUMNS
        data_start = self._find_data_start_row(df)
        logger.debug(
            'Data starts at row %d, table has %d rows x %d cols (merged=%s)',
            data_start,
            len(df),
            num_cols,
            merged_col,
        )
        i = data_start

        while i < len(df) - 1:
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
        """Parse a pair of Sberbank rows and return next index."""
        row_a = df.iloc[i]
        row_b = df.iloc[i + 1]

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

    def _parse_merged_layout(
        self,
        row_a: pd.Series,
        row_b: pd.Series,
        i: int,
        date: datetime,
        transactions: list[dict[str, Any]],
    ) -> int:
        """Parse 3-column merged layout."""
        col1_text = (
            str(row_a.iloc[SBERBANK_CATEGORY_COL]).strip()
            if len(row_a) > SBERBANK_CATEGORY_COL
            else ''
        )
        if col1_text == 'nan':
            col1_text = ''

        parts = col1_text.split('\n', 1)
        category = parts[0].strip() if parts else ''
        amount_text = parts[1].strip() if len(parts) > 1 else ''

        row_b_has_date = (
            self._extract_date(
                str(row_b.iloc[SBERBANK_DATE_COL]) if len(row_b) > 0 else '',
            )
            is not None
        )
        if row_b_has_date:
            self._add_transaction_if_valid(
                transactions,
                date,
                amount_text,
                category,
            )
            return i + 1

        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
                },
            )
        return i + 2

    def _parse_standard_layout(
        self,
        row_a: pd.Series,
        row_b: pd.Series,
        i: int,
        date: datetime,
        transactions: list[dict[str, Any]],
    ) -> int:
        """Parse 4-column standard layout."""
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
        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
                },
            )
        return i + 2

    def _add_transaction_if_valid(
        self,
        transactions: list[dict[str, Any]],
        date: datetime,
        amount_text: str,
        category: str,
    ) -> None:
        """Add transaction to list if amount is valid and non-zero."""
        amount = self._extract_sberbank_amount(amount_text)
        if amount is not None and amount != Decimal(0):
            transactions.append(
                {
                    'date': date,
                    'amount': amount,
                    'description': (category or 'Операция')[:250],
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
# Detection + factory
# ---------------------------------------------------------------------------


def _extract_pdf_text_for_detection(pdf_path: Path) -> str:
    """Extract raw text from the first page of a PDF for bank detection."""
    return extract_text(str(pdf_path), page_numbers=[0], maxpages=1)


def _create_parser(pdf_path: Path) -> BaseBankStatementParser:
    """Auto-detect bank from PDF content and return matching parser."""
    try:
        text = _extract_pdf_text_for_detection(pdf_path)
    except (OSError, ValueError) as e:
        logger.warning(
            'Could not extract text for bank detection '
            '(using generic parser): %s',
            e,
        )
        return _GenericBankParser(pdf_path)

    if RAIFFEISEN_BANK_NAME in text:
        logger.info('Detected bank: Raiffeisen')
        return _RaiffeisenBankParser(pdf_path)

    if SBERBANK_CREDIT_CARD_TITLE in text:
        logger.info('Detected bank: Sberbank credit card')
        return _SberbankParser(pdf_path)

    # Fallback: column-header-based detection
    if 'Поступления' in text and '№ П/П' in text:
        logger.info('Detected bank: Raiffeisen (via column headers)')
        return _RaiffeisenBankParser(pdf_path)

    if 'КАТЕГОРИЯ' in text and 'ОСТАТОК СРЕДСТВ' in text:
        logger.info('Detected bank: Sberbank (via column headers)')
        return _SberbankParser(pdf_path)

    logger.info('Unknown bank format, using generic parser')
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

    def parse(self) -> list[dict[str, Any]]:
        """Parse PDF and return list of {date, amount, description} dicts."""
        return self._delegate.parse()

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the delegate parser."""
        return getattr(self._delegate, name)


# ---------------------------------------------------------------------------
# process_bank_statement (unchanged public function)
# ---------------------------------------------------------------------------


@transaction.atomic
def process_bank_statement(
    pdf_path: str | Path,
    account: Account,
    user: User,
) -> dict[str, int]:
    """Process bank statement and create Income/Expense records.

    Args:
        pdf_path: Path to the PDF file.
        account: Account to associate transactions with.
        user: User who owns the account.

    Returns:
        Dictionary with income_count, expense_count, total_count.

    Raises:
        BankStatementParseError: If parsing fails.
    """
    parser = BankStatementParser(pdf_path)
    transactions = parser.parse()
    logger.info('Found %d transactions to process', len(transactions))

    income_count = 0
    expense_count = 0

    for idx, trans in enumerate(transactions):
        if idx % 10 == 0:
            logger.info(
                'Processing transaction %d/%d',
                idx + 1,
                len(transactions),
            )
        amount = trans['amount']
        description = trans['description']
        trans_date = trans['date']

        if amount > 0:
            category = _get_or_create_income_category(user, description)
            Income.objects.create(
                user=user,
                account=account,
                category=category,
                amount=abs(amount),
                date=trans_date,
            )
            # Update account balance for income (add money)
            account.balance += abs(amount)
            income_count += 1
        else:
            category = _get_or_create_expense_category(user, description)
            Expense.objects.create(
                user=user,
                account=account,
                category=category,
                amount=abs(amount),
                date=trans_date,
            )
            # Update account balance for expense (subtract money)
            account.balance -= abs(amount)
            expense_count += 1

    # Save account balance after all transactions
    account.save()

    logger.info(
        'Finished processing: %d income, %d expenses',
        income_count,
        expense_count,
    )
    return {
        'income_count': income_count,
        'expense_count': expense_count,
        'total_count': income_count + expense_count,
    }


def _get_or_create_income_category(user: User, name: str) -> IncomeCategory:
    category, _ = IncomeCategory.objects.get_or_create(
        user=user,
        name=name[:250],
    )
    return category


def _get_or_create_expense_category(user: User, name: str) -> ExpenseCategory:
    category, _ = ExpenseCategory.objects.get_or_create(
        user=user,
        name=name[:250],
    )
    return category
