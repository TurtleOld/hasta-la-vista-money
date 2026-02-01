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

# Constants for bank statement parsing
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
            tables = camelot.read_pdf(
                str(self.pdf_path),
                flavor='stream',
                pages='all',
            )
            transactions = []

            for table in tables:
                df = table.df
                # Only process tables that look like transaction tables
                if (
                    len(df.columns) >= MIN_TABLE_COLUMNS
                    and self._is_transaction_table(df)
                ):
                    parsed_transactions = self._parse_table(df)
                    transactions.extend(parsed_transactions)

            return transactions
        except BankStatementParseError:
            raise
        except Exception as e:
            logger.exception('Failed to parse PDF file: %s', self.pdf_path)
            error_msg = f'Не удалось обработать PDF файл: {e!s}'
            raise BankStatementParseError(error_msg) from e

    def _is_transaction_table(self, df: pd.DataFrame) -> bool:
        """Check if DataFrame is a transaction table.

        Args:
            df: DataFrame to check.

        Returns:
            True if this looks like a transaction table.
        """
        # Look for transaction numbers in first column
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

        # Skip header rows and find transaction rows
        for row_idx, row in df.iterrows():
            try:
                # Check if this row contains transaction number
                first_col = str(row.iloc[0]) if len(row) > 0 else ''

                # Skip header and empty rows
                if not first_col or first_col == 'nan':
                    continue

                # Try to extract transaction number (should be a digit)
                trans_num = self._extract_transaction_number(first_col)
                if trans_num is None:
                    continue

                # Parse the transaction row
                row_index = int(row_idx) if isinstance(row_idx, int) else 0
                transaction = self._parse_transaction_row(
                    row, df, row_index
                )
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
        # Look for single digit or number at start of line
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
        # Column structure:
        # 0: Transaction number
        # 1: Date (sometimes)
        # 2: Document number
        # 3: Income (Поступления) with "+" sign
        # 4: Expenses (Расходы) with "-" sign
        # 5: Description (Детали операции)

        # Extract amount from current row
        # Search in all columns starting from column 2
        # Different table formats have amounts in different columns
        amount = None
        description_col_idx = None

        for col_idx in range(2, len(row)):
            col_text = str(row.iloc[col_idx])
            extracted_amount = self._extract_amount_from_column(col_text)

            if extracted_amount is not None:
                # Check if this is income (positive) or expense (negative)
                if '+' in col_text:
                    amount = extracted_amount
                elif '-' in col_text:
                    amount = -extracted_amount
                else:
                    # If no sign in text, assume positive
                    amount = extracted_amount

                # Determine description column based on table format
                description_col_idx = (
                    5 if len(row) >= MIN_STANDARD_COLUMNS else col_idx + 1
                )
                break

        if amount is None:
            return None

        # Extract date - look backwards from current row
        # Check both column 0 and column 1 for dates (different table formats)
        date = None
        for i in range(index, max(0, index - 5), -1):
            check_row = df.iloc[i]

            # Try column 0 first (some tables have date here)
            if len(check_row) > 0:
                date_text = str(check_row.iloc[0])
                date = self._extract_date(date_text)
                if date:
                    break

            # Try column 1 (execution date in standard format)
            if len(check_row) > 1:
                date_text = str(check_row.iloc[1])
                date = self._extract_date(date_text)
                if date:
                    break

        if date is None:
            # If no date found, skip this transaction
            return None

        # Extract description from current row and subsequent rows
        description_parts = []

        # Use the description column found during amount extraction
        # or fallback to column 5 for older table format
        if description_col_idx is None:
            description_col_idx = 5

        if len(row) > description_col_idx:
            desc_text = str(row.iloc[description_col_idx])
            if desc_text and desc_text != 'nan':
                desc_text = desc_text.strip()
                if desc_text:
                    description_parts.append(desc_text)

        # Look at subsequent rows for additional description parts
        # Continue until we hit a new transaction
        for next_idx in range(index + 1, min(index + 10, len(df))):
            next_row = df.iloc[next_idx]

            # Stop if next row has a transaction number (new transaction)
            if len(next_row) > 0:
                first_col = str(next_row.iloc[0])
                if self._extract_transaction_number(first_col) is not None:
                    break

            # Extract description from the same column
            if len(next_row) > description_col_idx:
                desc_text = str(next_row.iloc[description_col_idx])
                if desc_text and desc_text != 'nan':
                    desc_text = desc_text.strip()
                    # Skip account numbers, card numbers, and "Со счета:" lines
                    if desc_text and not re.match(
                        r'^(\d{5,}|\*\d{4}|Со счета:|На счет:)',
                        desc_text,
                    ):
                        description_parts.append(desc_text)

        # Join all parts and clean up the description
        description = ' '.join(description_parts).strip()

        # Extract the main description (first meaningful part before details)
        # For ATM withdrawals, the format is:
        # "Выдача наличных средств со счета через банкомат DD.MM.YY, AMOUNT руб., ATM XXXX, г City, Address"
        # We want to extract just "Выдача наличных средств со счета через банкомат"
        description = self._clean_description(description)
        if not description:
            description = 'Операция'

        return {
            'date': date,
            'amount': amount,
            'description': description[:250],
        }

    def _extract_amount_from_column(self, text: str) -> Decimal | None:
        """Extract amount from column text.

        Args:
            text: Column text containing amount.

        Returns:
            Decimal amount or None.
        """
        if not text or text == 'nan':
            return None

        # Look for amounts with currency symbol ₽
        # Format: "+ 120 000,00 ₽" or "- 1 080,00 ₽"
        # Must have currency symbol and comma for cents
        amount_pattern = r'[+-]?\s*(\d+(?:\s+\d+)*,\d{2})\s*₽'
        match = re.search(amount_pattern, text)

        if match:
            amount_str = match.group(1)
            # Remove spaces (thousand separators) and replace comma with dot
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

        # For ATM operations, extract just the operation type
        # Pattern: "Выдача наличных средств со счета через банкомат DD.MM.YY, ..."
        atm_match = re.match(
            r'^(Выдача наличных(?:\s+средств)?(?:\s+со счета)?(?:\s+через банкомат)?)',
            description,
            re.IGNORECASE,
        )
        if atm_match:
            return 'Выдача наличных'

        # For card payments, extract merchant name
        # Pattern: "MERCHANT_NAME" or with additional details
        # Remove trailing technical info like dates, amounts, addresses
        # Common patterns to remove:
        # - Dates: DD.MM.YY or DD.MM.YYYY
        # - Amounts: XXXXX руб. or XXXXX,XX ₽
        # - ATM/terminal numbers: ATM XXXX, терминал XXXX
        # - Addresses starting with: г, город, ул, пл, д, стр

        # Remove date patterns (DD.MM.YY or DD.MM.YYYY)
        cleaned = re.sub(r'\s+\d{2}\.\d{2}\.\d{2,4}', '', description)

        # Remove amount patterns (XXXXX руб. or XXXXX,XX ₽)
        cleaned = re.sub(
            r'\s*\d+(?:\s?\d+)*(?:,\d{2})?\s*(?:руб\.?|₽)',
            '',
            cleaned,
        )

        # Remove ATM/terminal numbers
        cleaned = re.sub(
            r'\s*(?:ATM|терминал)\s*\d+',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )

        # Remove addresses (г City, улица, площадь, дом, строение, etc.)
        cleaned = re.sub(
            r'\s*[,;]?\s*г\s+[^,]+(?:,\s*[^,]+)*$',
            '',
            cleaned,
        )

        # Remove trailing punctuation and whitespace
        cleaned = cleaned.strip(' ,;.')

        # If we stripped everything, return original (truncated)
        if not cleaned:
            # Return first part before comma or specific details
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
        # First try to extract date with time (DD.MM.YYYY HH:MM)
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
                )
                # Validate year (should be reasonable)
                if MIN_YEAR <= parsed_date.year <= MAX_YEAR:
                    return parsed_date
            except ValueError:
                pass

        # Fallback: extract date only (DD.MM.YYYY)
        date_pattern = r'\b(\d{2}\.\d{2}\.\d{4})\b'
        match = re.search(date_pattern, text)
        if match:
            try:
                date_str = match.group(1)
                parsed_date = datetime.strptime(date_str, '%d.%m.%Y')
                # Validate year (should be reasonable)
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
    parser = BankStatementParser(pdf_path)
    transactions = parser.parse()

    income_count = 0
    expense_count = 0

    for trans in transactions:
        amount = trans['amount']
        description = trans['description']
        trans_date = timezone.make_aware(trans['date'])

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
