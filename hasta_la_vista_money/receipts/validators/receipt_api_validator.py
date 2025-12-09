"""Validator for receipts API requests."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from core.repositories.protocols import ReceiptRepositoryProtocol


@dataclass
class ValidationResult:
    """Result of validation operation."""

    is_valid: bool
    error: str | None = None
    user: 'User | None' = None
    account: 'Account | None' = None


class ReceiptAPIValidator:
    """Validator for receipts API requests.

    Validates request data, checks required fields, validates user and account,
    and checks for existing receipts.
    """

    def __init__(
        self,
        receipt_repository: 'ReceiptRepositoryProtocol',
    ) -> None:
        """Initialize validator with required repositories.

        Args:
            receipt_repository: Repository for receipt operations
        """
        self.receipt_repository = receipt_repository

    def validate_json_data(
        self,
        request_data: dict[str, Any],
    ) -> ValidationResult:
        """Validate JSON request data structure.

        Args:
            request_data: Parsed JSON data from request

        Returns:
            ValidationResult with validation status and error message if invalid
        """
        required_fields = [
            'user',
            'finance_account',
            'receipt_date',
            'total_sum',
            'seller',
            'product',
        ]
        missing_fields = [
            field for field in required_fields if not request_data.get(field)
        ]

        if missing_fields:
            return ValidationResult(
                is_valid=False,
                error=f'Missing required fields: {", ".join(missing_fields)}',
            )

        return ValidationResult(is_valid=True)

    def validate_user_and_account(
        self,
        user_id: int | None,
        account_id: int | None,
    ) -> ValidationResult:
        """Validate user and account existence and relationship.

        Args:
            user_id: User ID from request
            account_id: Account ID from request

        Returns:
            ValidationResult with user and account if valid, error otherwise
        """
        if user_id is None:
            return ValidationResult(
                is_valid=False,
                error='User ID is required',
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return ValidationResult(
                is_valid=False,
                error=f'User with id {user_id} does not exist',
            )

        if account_id is None:
            return ValidationResult(
                is_valid=False,
                error='Account ID is required',
            )

        try:
            account = Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return ValidationResult(
                is_valid=False,
                error=(
                    f'Account with id {account_id} does not exist '
                    f'or does not belong to user {user_id}'
                ),
            )

        return ValidationResult(
            is_valid=True,
            user=user,
            account=account,
        )

    def check_receipt_exists(
        self,
        request_data: dict[str, Any],
        user: 'User',
    ) -> bool:
        """Check if receipt with given data already exists for user.

        Args:
            request_data: Request data containing receipt information
            user: User to check receipts for

        Returns:
            True if receipt exists, False otherwise
        """
        receipt_date = request_data.get('receipt_date')
        total_sum = request_data.get('total_sum')

        if receipt_date is None or total_sum is None:
            return False

        # Parse receipt_date if it's a string
        if isinstance(receipt_date, str):
            try:
                receipt_date = datetime.fromisoformat(receipt_date)
            except (ValueError, AttributeError):
                return False

        # Convert total_sum to Decimal if needed
        if not isinstance(total_sum, Decimal):
            try:
                total_sum = Decimal(str(total_sum))
            except (ValueError, TypeError):
                return False

        # Use direct model query as repository doesn't have this specific filter
        return Receipt.objects.filter(
            user=user,
            receipt_date=receipt_date,
            total_sum=total_sum,
        ).exists()
