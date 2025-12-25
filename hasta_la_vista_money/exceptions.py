"""Custom exceptions for domain-specific errors.

This module defines custom exceptions for different domain areas,
providing clear error messages and better error handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal


class AccountError(ValueError):
    """Base exception for account-related errors."""


class InsufficientFundsError(AccountError):
    """Raised when account has insufficient funds for an operation.

    Attributes:
        account_id: ID of the account with insufficient funds.
        balance: Current account balance.
        required: Required amount for the operation.
    """

    def __init__(
        self,
        account_id: int,
        balance: Decimal,
        required: Decimal,
        message: str | None = None,
    ) -> None:
        """Initialize InsufficientFundsError.

        Args:
            account_id: ID of the account.
            balance: Current balance.
            required: Required amount.
            message: Optional custom error message.
        """
        self.account_id = account_id
        self.balance = balance
        self.required = required
        if message is None:
            message = (
                f'Account {account_id} has balance {balance}, '
                f'but required {required}'
            )
        super().__init__(message)


class AccountNotFoundError(AccountError):
    """Raised when account is not found or user doesn't have access.

    Attributes:
        account_id: ID of the account that was not found.
    """

    def __init__(self, account_id: int, message: str | None = None) -> None:
        """Initialize AccountNotFoundError.

        Args:
            account_id: ID of the account.
            message: Optional custom error message.
        """
        self.account_id = account_id
        if message is None:
            message = f'Account {account_id} not found or access denied'
        super().__init__(message)


class ReceiptError(ValueError):
    """Base exception for receipt-related errors."""


class ReceiptNotFoundError(ReceiptError):
    """Raised when receipt is not found.

    Attributes:
        receipt_id: ID of the receipt that was not found.
    """

    def __init__(self, receipt_id: int, message: str | None = None) -> None:
        """Initialize ReceiptNotFoundError.

        Args:
            receipt_id: ID of the receipt.
            message: Optional custom error message.
        """
        self.receipt_id = receipt_id
        if message is None:
            message = f'Receipt {receipt_id} not found'
        super().__init__(message)


class ReceiptAlreadyExistsError(ReceiptError):
    """Raised when receipt with same number already exists.

    Attributes:
        receipt_number: Number of the duplicate receipt.
    """

    def __init__(
        self,
        receipt_number: int,
        message: str | None = None,
    ) -> None:
        """Initialize ReceiptAlreadyExistsError.

        Args:
            receipt_number: Number of the duplicate receipt.
            message: Optional custom error message.
        """
        self.receipt_number = receipt_number
        if message is None:
            message = f'Receipt with number {receipt_number} already exists'
        super().__init__(message)


class ExpenseError(ValueError):
    """Base exception for expense-related errors."""


class ExpenseNotFoundError(ExpenseError):
    """Raised when expense is not found.

    Attributes:
        expense_id: ID of the expense that was not found.
    """

    def __init__(self, expense_id: int, message: str | None = None) -> None:
        """Initialize ExpenseNotFoundError.

        Args:
            expense_id: ID of the expense.
            message: Optional custom error message.
        """
        self.expense_id = expense_id
        if message is None:
            message = f'Expense {expense_id} not found'
        super().__init__(message)


class IncomeError(ValueError):
    """Base exception for income-related errors."""


class IncomeNotFoundError(IncomeError):
    """Raised when income is not found.

    Attributes:
        income_id: ID of the income that was not found.
    """

    def __init__(self, income_id: int, message: str | None = None) -> None:
        """Initialize IncomeNotFoundError.

        Args:
            income_id: ID of the income.
            message: Optional custom error message.
        """
        self.income_id = income_id
        if message is None:
            message = f'Income {income_id} not found'
        super().__init__(message)
