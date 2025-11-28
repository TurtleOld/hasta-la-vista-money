from datetime import UTC, date, datetime
from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.income.repositories.income_repository import (
    IncomeRepository,
)
from hasta_la_vista_money.users.models import User


class IncomeRepositoryTest(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.category = IncomeCategory.objects.filter(user=self.user).first()
        self.repository = IncomeRepository()

    def test_get_by_id(self) -> None:
        if self.category:
            income = Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_id(income.pk)
            self.assertEqual(result.pk, income.pk)

    def test_get_by_user(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_user(self.user)
            self.assertGreaterEqual(result.count(), 1)

    def test_get_by_user_with_related(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_user_with_related(self.user)
            self.assertGreaterEqual(result.count(), 1)
            income = result.first()
            if income:
                self.assertIsNotNone(income.user)
                self.assertIsNotNone(income.category)
                self.assertIsNotNone(income.account)

    def test_get_by_period(self) -> None:
        if self.category:
            start_date = date(2025, 1, 1)
            end_date = date(2025, 12, 31)
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.make_aware(datetime(2025, 6, 15, tzinfo=UTC)),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_period(
                self.user, start_date, end_date
            )
            self.assertGreaterEqual(result.count(), 1)

    def test_filter_by_user_and_date_range(self) -> None:
        if self.category:
            start_datetime = timezone.make_aware(
                datetime(2025, 1, 1, tzinfo=UTC)
            )
            end_datetime = timezone.make_aware(
                datetime(2025, 12, 31, tzinfo=UTC)
            )
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.make_aware(datetime(2025, 6, 15, tzinfo=UTC)),
                amount=Decimal('1000.00'),
            )
            result = self.repository.filter_by_user_and_date_range(
                self.user,
                start_datetime,
                end_datetime,
            )
            self.assertGreaterEqual(result.count(), 1)

    def test_get_by_category(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_category(self.user, self.category)
            self.assertGreaterEqual(result.count(), 1)

    def test_get_by_account(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_by_account(self.user, self.account.pk)
            self.assertGreaterEqual(result.count(), 1)

    def test_create_income(self) -> None:
        if self.category:
            income = self.repository.create_income(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            self.assertIsNotNone(income.pk)
            self.assertEqual(income.user, self.user)

    def test_filter(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.filter(user=self.user)
            self.assertGreaterEqual(result.count(), 1)

    def test_filter_with_select_related(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.filter_with_select_related(
                'user',
                'category',
                user=self.user,
            )
            self.assertGreaterEqual(result.count(), 1)
            income = result.first()
            if income:
                self.assertIsNotNone(income.user)
                self.assertIsNotNone(income.category)

    def test_filter_by_account(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.filter_by_account(self.account)
            self.assertGreaterEqual(result.count(), 1)

    def test_get_aggregated_by_date(self) -> None:
        if self.category:
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.now(),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_aggregated_by_date(self.user)
            self.assertGreaterEqual(result.count(), 0)

    def test_get_top_categories(self) -> None:
        if self.category:
            year_start = timezone.make_aware(datetime(2025, 1, 1, tzinfo=UTC))
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.make_aware(datetime(2025, 6, 15, tzinfo=UTC)),
                amount=Decimal('1000.00'),
            )
            result = self.repository.get_top_categories(
                self.user, year_start, limit=10
            )
            self.assertGreaterEqual(result.count(), 0)

    def test_filter_by_user_category_and_month(self) -> None:
        if self.category:
            test_month = date(2025, 6, 1)
            Income.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                date=timezone.make_aware(datetime(2025, 6, 15, tzinfo=UTC)),
                amount=Decimal('1000.00'),
            )
            result = self.repository.filter_by_user_category_and_month(
                self.user,
                self.category,
                test_month,
            )
            self.assertGreaterEqual(result.count(), 0)
