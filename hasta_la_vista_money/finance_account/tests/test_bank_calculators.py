"""Tests for bank calculators."""

from calendar import monthrange
from datetime import datetime, time
from unittest.mock import MagicMock

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.services.bank_calculators import (
    DefaultBankCalculator,
    RaiffeisenbankCalculator,
    SberbankCalculator,
    create_bank_calculator,
)
from hasta_la_vista_money.finance_account.services.bank_constants import (
    BANK_DEFAULT,
    BANK_RAIFFEISENBANK,
    BANK_SBERBANK,
)
from hasta_la_vista_money.users.factories import UserFactory


class TestSberbankCalculator(TestCase):
    """Test cases for SberbankCalculator."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.user = UserFactory()
        self.account = AccountFactory(
            user=self.user,
            bank=BANK_SBERBANK,
            type_account='CreditCard',
        )
        self.calculator = SberbankCalculator()
        self.purchase_start = timezone.make_aware(
            datetime(2024, 1, 1, 0, 0, 0),  # noqa: DTZ001
        )
        self.purchase_end = timezone.make_aware(
            datetime(2024, 1, 31, 23, 59, 59),  # noqa: DTZ001
        )

    def test_calculate_grace_period(self) -> None:
        """Test grace period calculation for Sberbank."""
        grace_end, payments_start, payments_end = (
            self.calculator.calculate_grace_period(
                self.account,
                self.purchase_start,
                self.purchase_end,
            )
        )

        expected_grace_end_date = self.purchase_start + relativedelta(
            months=constants.GRACE_PERIOD_MONTHS_SBERBANK,
        )
        expected_grace_end = timezone.make_aware(
            datetime.combine(
                expected_grace_end_date.replace(
                    day=monthrange(
                        expected_grace_end_date.year,
                        expected_grace_end_date.month,
                    )[1],
                ),
                time.max,
            ),
        )

        self.assertIsInstance(grace_end, datetime)
        self.assertIsInstance(payments_start, datetime)
        self.assertIsInstance(payments_end, datetime)
        self.assertEqual(grace_end, expected_grace_end)
        self.assertEqual(
            payments_start,
            self.purchase_end + relativedelta(seconds=constants.ONE_SECOND),
        )
        self.assertEqual(payments_end, grace_end)


class TestRaiffeisenbankCalculator(TestCase):
    """Test cases for RaiffeisenbankCalculator."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.user = UserFactory()
        self.account = AccountFactory(
            user=self.user,
            bank=BANK_RAIFFEISENBANK,
            type_account='CreditCard',
        )
        self.expense_repository = MagicMock()
        self.receipt_repository = MagicMock()
        self.calculator = RaiffeisenbankCalculator(
            expense_repository=self.expense_repository,
            receipt_repository=self.receipt_repository,
        )
        self.purchase_start = timezone.make_aware(
            datetime(2024, 1, 1, 0, 0, 0),  # noqa: DTZ001
        )
        self.purchase_end = timezone.make_aware(
            datetime(2024, 1, 31, 23, 59, 59),  # noqa: DTZ001
        )

    def test_calculate_grace_period_with_first_purchase(self) -> None:
        """Test grace period calculation with first purchase."""
        first_purchase = timezone.make_aware(
            datetime(2024, 1, 5, 12, 0, 0),  # noqa: DTZ001
        )

        mock_expense = MagicMock()
        mock_expense.date = first_purchase
        self.expense_repository.filter.return_value.order_by.return_value.first.return_value = (  # noqa: E501
            mock_expense
        )
        self.receipt_repository.filter.return_value.order_by.return_value.first.return_value = (  # noqa: E501
            None
        )

        grace_end, payments_start, payments_end = (
            self.calculator.calculate_grace_period(
                self.account,
                self.purchase_start,
                self.purchase_end,
            )
        )

        expected_grace_end = first_purchase + relativedelta(
            days=constants.GRACE_PERIOD_DAYS_RAIFFEISENBANK,
        )
        expected_grace_end = timezone.make_aware(
            datetime.combine(expected_grace_end.date(), time.max),
        )

        self.assertEqual(grace_end, expected_grace_end)
        self.assertEqual(
            payments_start,
            self.purchase_end + relativedelta(seconds=constants.ONE_SECOND),
        )
        self.assertEqual(payments_end, grace_end)

    def test_calculate_grace_period_without_first_purchase(self) -> None:
        """Test grace period calculation without first purchase."""
        self.expense_repository.filter.return_value.order_by.return_value.first.return_value = (  # noqa: E501
            None
        )
        self.receipt_repository.filter.return_value.order_by.return_value.first.return_value = (  # noqa: E501
            None
        )

        grace_end, payments_start, payments_end = (
            self.calculator.calculate_grace_period(
                self.account,
                self.purchase_start,
                self.purchase_end,
            )
        )

        self.assertEqual(grace_end, self.purchase_end)
        self.assertEqual(
            payments_start,
            self.purchase_end + relativedelta(seconds=constants.ONE_SECOND),
        )
        self.assertEqual(payments_end, grace_end)


class TestDefaultBankCalculator(TestCase):
    """Test cases for DefaultBankCalculator."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.user = UserFactory()
        self.account = AccountFactory(user=self.user, bank=BANK_DEFAULT)
        self.calculator = DefaultBankCalculator()
        self.purchase_start = timezone.make_aware(
            datetime(2024, 1, 1, 0, 0, 0),  # noqa: DTZ001
        )
        self.purchase_end = timezone.make_aware(
            datetime(2024, 1, 31, 23, 59, 59),  # noqa: DTZ001
        )

    def test_calculate_grace_period(self) -> None:
        """Test default grace period calculation."""
        grace_end, payments_start, payments_end = (
            self.calculator.calculate_grace_period(
                self.account,
                self.purchase_start,
                self.purchase_end,
            )
        )

        self.assertEqual(grace_end, self.purchase_end)
        self.assertEqual(
            payments_start,
            self.purchase_end + relativedelta(seconds=constants.ONE_SECOND),
        )
        self.assertEqual(payments_end, grace_end)


class TestCreateBankCalculator(TestCase):
    """Test cases for create_bank_calculator factory."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.expense_repository = MagicMock()
        self.receipt_repository = MagicMock()

    def test_create_sberbank_calculator(self) -> None:
        """Test creating Sberbank calculator."""
        calculator = create_bank_calculator(BANK_SBERBANK)
        self.assertIsInstance(calculator, SberbankCalculator)

    def test_create_raiffeisenbank_calculator(self) -> None:
        """Test creating Raiffeisenbank calculator."""
        calculator = create_bank_calculator(
            BANK_RAIFFEISENBANK,
            expense_repository=self.expense_repository,
            receipt_repository=self.receipt_repository,
        )
        self.assertIsInstance(calculator, RaiffeisenbankCalculator)

    def test_create_raiffeisenbank_calculator_without_repositories(
        self,
    ) -> None:
        """Test creating Raiffeisenbank calculator without repositories."""
        with self.assertRaises(ValueError):
            create_bank_calculator(BANK_RAIFFEISENBANK)

    def test_create_default_calculator(self) -> None:
        """Test creating default calculator for unknown bank."""
        calculator = create_bank_calculator(BANK_DEFAULT)
        self.assertIsInstance(calculator, DefaultBankCalculator)

    def test_create_calculator_for_unknown_bank(self) -> None:
        """Test creating calculator for unknown bank."""
        calculator = create_bank_calculator('UNKNOWN_BANK')
        self.assertIsInstance(calculator, DefaultBankCalculator)
