"""Service for parsing bank statements from PDF files."""

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import camelot
import pandas as pd
from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User

logger = logging.getLogger(__name__)

MIN_TABLE_COLUMNS = 5
MIN_STANDARD_COLUMNS = 7
MIN_YEAR = 2000
MAX_YEAR = 2100


class BankStatementParseError(Exception):
    """Exception raised when parsing bank statement fails."""


class BankStatementParser:
    """Parser for bank statement PDF files."""

    def __init__(self, pdf_path: str | Path) -> None:
        """Initialize parser with PDF file path.

        Args:
            pdf_path: Path to the PDF file.
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            error_msg = f'PDF file not found: {pdf_path}'
            raise FileNotFoundError(error_msg)

    def parse(self) -> list[dict[str, Any]]:
        """Parse PDF and extract transaction data.

        Returns:
            List of transaction dictionaries with keys:
            - date: datetime object
            - amount: Decimal object
            - description: string

        Raises:
            BankStatementParseError: If parsing fails.
        """
        try:
            logger.info('Starting PDF parsing: %s', self.pdf_path)
            tables = camelot.read_pdf(
                str(self.pdf_path),
                flavor='stream',
                pages='all',
                suppress_stdout=True,
            )
            logger.info('Found %d tables in PDF', len(tables))
            transactions = []

            for idx, table in enumerate(tables):
                logger.info('Processing table %d/%d', idx + 1, len(tables))
                table_data = table.df
                if len(
                    table_data.columns,
                ) >= MIN_TABLE_COLUMNS and self._is_transaction_table(
                    table_data,
                ):
                    parsed_transactions = self._parse_table(table_data)
                    logger.info(
                        'Extracted %d transactions from table %d',
                        len(parsed_transactions),
                        idx + 1,
                    )
                    transactions.extend(parsed_transactions)

            logger.info(
                'Parsing completed. Total transactions: %d',
                len(transactions),
            )
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('Failed to parse PDF file: %s', self.pdf_path)
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e
        else:
            return transactions

    def _is_transaction_table(self, df: pd.DataFrame) -> bool:
        """Check if DataFrame is a transaction table.

        Args:
            df: DataFrame to check.

        Returns:
            True if this looks like a transaction table.
        """
        for _index, row in df.iterrows():
            if len(row) > 0:
                first_col = str(row.iloc[0])
                if self._extract_transaction_number(first_col) is not None:
                    return True
        return False

    def _parse_table(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Parse a single table from the PDF.

        Args:
            df: DataFrame containing the table data.

        Returns:
            List of parsed transactions.
        """
        transactions = []

        for row_idx, row in df.iterrows():
            try:
                first_col = str(row.iloc[0]) if len(row) > 0 else ''

                if not first_col or first_col == 'nan':
                    continue

                trans_num = self._extract_transaction_number(first_col)
                if trans_num is None:
                    continue

                row_index = int(row_idx) if isinstance(row_idx, int) else 0
                transaction = self._parse_transaction_row(row, df, row_index)
                if transaction:
                    transactions.append(transaction)

            except ValueError as e:
                logger.warning(
                    'Failed to parse row %s: %s',
                    row_idx,
                    e,
                )
                continue

        return transactions

    def _extract_transaction_number(self, text: str) -> int | None:
        """Extract transaction number from text.

        Args:
            text: Text to search for transaction number.

        Returns:
            Transaction number or None.
        """
        match = re.match(r'^\s*(\d+)\s*$', text.strip())
        if match:
            return int(match.group(1))
        return None

    def _parse_transaction_row(
        self,
        row: pd.Series,
        df: pd.DataFrame,
        index: int,
    ) -> dict[str, Any] | None:
        """Parse a transaction row.

        Args:
            row: Current row containing transaction number.
            df: Full dataframe for context.
            index: Current row index.

        Returns:
            Parsed transaction dict or None if invalid.
        """
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
        """Extract amount from row.

        Args:
            row: Row to extract amount from.

        Returns:
            Decimal amount or None.
        """
        for col_idx in range(2, len(row)):
            col_text = str(row.iloc[col_idx])
            extracted_amount = self._extract_amount_from_column(col_text)

            if extracted_amount is not None:
                if '+' in col_text:
                    return extracted_amount
                if '-' in col_text:
                    return -extracted_amount
                return extracted_amount
        return None

    def _get_description_column_index(self, row: pd.Series) -> int:
        """Get description column index.

        Args:
            row: Row to analyze.

        Returns:
            Column index for description.
        """
        return 5 if len(row) >= MIN_STANDARD_COLUMNS else 2

    def _extract_date_from_context(
        self,
        df: pd.DataFrame,
        index: int,
    ) -> datetime | None:
        """Extract date from context rows.

        Args:
            df: Full dataframe.
            index: Current row index.

        Returns:
            Extracted datetime or None.
        """
        for i in range(index, max(0, index - 5), -1):
            check_row = df.iloc[i]

            for col_idx in range(min(2, len(check_row))):
                if len(check_row) > col_idx:
                    date_text = str(check_row.iloc[col_idx])
                    date = self._extract_date(date_text)
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
        """Extract description from row and following rows.

        Args:
            row: Current row.
            df: Full dataframe.
            index: Current row index.
            description_col_idx: Column index for description.

        Returns:
            Extracted description string.
        """
        description_parts = []

        if len(row) > description_col_idx:
            desc_text = str(row.iloc[description_col_idx])
            if desc_text and desc_text != 'nan':
                desc_text = desc_text.strip()
                if desc_text:
                    description_parts.append(desc_text)

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
                        description_parts.append(desc_text)

        return ' '.join(description_parts).strip()

    def _extract_amount_from_column(self, text: str) -> Decimal | None:
        """Extract amount from column text.

        Args:
            text: Column text containing amount.

        Returns:
            Decimal amount or None.
        """
        if not text or text == 'nan':
            return None

        amount_pattern = r'[+-]?\s*(\d+(?:\s+\d+)*,\d{2})\s*₽'
        match = re.search(amount_pattern, text)

        if match:
            amount_str = match.group(1)
            amount_str = amount_str.replace(' ', '').replace(',', '.')
            try:
                return Decimal(amount_str)
            except InvalidOperation:
                pass

        return None

    def _clean_description(self, description: str) -> str:
        """Clean and normalize transaction description.

        Extracts the main meaningful part of the description,
        removing technical details like dates, amounts, ATM numbers, addresses.

        Args:
            description: Raw description text.

        Returns:
            Cleaned description string.
        """
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

        cleaned = re.sub(
            r'\s*[,;]?\s*г\s+[^,]+(?:,\s*[^,]+)*$',
            '',
            cleaned,
        )

        cleaned = cleaned.strip(' ,;.')

        if not cleaned:
            parts = description.split(',')
            if parts:
                return parts[0].strip()[:100]
            return description[:100]

        return cleaned

    def _extract_date(self, text: str) -> datetime | None:
        """Extract date from text.

        Args:
            text: Text to search for date.

        Returns:
            datetime object or None if no date found.
        """
        datetime_pattern = r'\b(\d{2}\.\d{2}\.\d{4})\s+(\d{2}):(\d{2})\b'
        match = re.search(datetime_pattern, text)
        if match:
            try:
                date_str = match.group(1)
                hour = match.group(2)
                minute = match.group(3)
                full_datetime_str = f'{date_str} {hour}:{minute}'
                parsed_date = datetime.strptime(
                    full_datetime_str,
                    '%d.%m.%Y %H:%M',
                ).replace(tzinfo=timezone.get_current_timezone())
                if MIN_YEAR <= parsed_date.year <= MAX_YEAR:
                    return parsed_date
            except ValueError:
                pass

        date_pattern = r'\b(\d{2}\.\d{2}\.\d{4})\b'
        match = re.search(date_pattern, text)
        if match:
            try:
                date_str = match.group(1)
                parsed_date = datetime.strptime(date_str, '%d.%m.%Y').replace(
                    tzinfo=timezone.get_current_timezone(),
                )
                if MIN_YEAR <= parsed_date.year <= MAX_YEAR:
                    return parsed_date
            except ValueError:
                pass
        return None


@transaction.atomic
def process_bank_statement(
    pdf_path: str | Path,
    account: Account,
    user: User,
) -> dict[str, int]:
    """Process bank statement and create transactions.

    Args:
        pdf_path: Path to the PDF file.
        account: Account to associate transactions with.
        user: User who owns the account.

    Returns:
        Dictionary with counts of created transactions:
        - income_count: Number of income transactions created.
        - expense_count: Number of expense transactions created.
        - total_count: Total number of transactions created.

    Raises:
        BankStatementParseError: If parsing fails.
    """
    logger.info('Creating BankStatementParser')
    parser = BankStatementParser(pdf_path)
    logger.info('Parsing PDF')
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
            expense_count += 1

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


def _get_or_create_income_category(
    user: User,
    name: str,
) -> IncomeCategory:
    """Get or create income category.

    Args:
        user: User who owns the category.
        name: Category name.

    Returns:
        IncomeCategory instance.
    """
    category, _ = IncomeCategory.objects.get_or_create(
        user=user,
        name=name[:250],
    )
    return category


def _get_or_create_expense_category(
    user: User,
    name: str,
) -> ExpenseCategory:
    """Get or create expense category.

    Args:
        user: User who owns the category.
        name: Category name.

    Returns:
        ExpenseCategory instance.
    """
    category, _ = ExpenseCategory.objects.get_or_create(
        user=user,
        name=name[:250],
    )
    return category
