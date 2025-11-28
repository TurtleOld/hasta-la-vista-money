from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, ClassVar

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.services.generate_dates import (
    DateListGenerator,
    generate_date_list,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from django.db.models import QuerySet


class DateListGeneratorTest(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'expense_cat.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_init(self) -> None:
        generator = DateListGenerator(user=self.user, type_='expense')
        self.assertEqual(generator.user, self.user)
        self.assertEqual(generator.type_, 'expense')

    def test_actual_date_from_datetime(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        test_datetime = timezone.make_aware(
            datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        )
        actual = generator._actual_date(test_datetime)
        self.assertEqual(actual, date(2025, 1, 15))

    def test_actual_date_from_date(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        test_date_obj = date(2025, 1, 15)
        actual = generator._actual_date(test_date_obj)
        self.assertEqual(actual, test_date_obj)

    def test_actual_date_from_queryset(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        DateList.objects.create(user=self.user, date=date(2025, 1, 15))
        queryset: 'QuerySet[DateList]' = DateList.objects.filter(user=self.user)
        actual = generator._actual_date(queryset)
        self.assertEqual(actual, date(2025, 1, 15))

    def test_actual_date_from_empty_queryset(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        queryset: QuerySet[DateList] = DateList.objects.filter(
            user=self.user, date__year=3000
        )
        with self.assertRaises(ValueError):
            generator._actual_date(queryset)

    def test_start_date_with_existing_dates(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))
        start = generator._start_date(date(2025, 1, 1))
        self.assertIsInstance(start, date)

    def test_start_date_without_existing_dates(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        actual = date(2025, 1, 1)
        start = generator._start_date(actual)
        self.assertEqual(start, actual)

    def test_month_sequence(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        start = date(2025, 1, 1)
        months = generator._month_sequence(start, 3)
        self.assertEqual(len(months), 3)
        self.assertEqual(months[0], date(2025, 1, 1))
        self.assertEqual(months[1], date(2025, 2, 1))
        self.assertEqual(months[2], date(2025, 3, 1))

    def test_ensure_dates_creates_missing(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        months = [date(2025, 1, 1), date(2025, 2, 1)]
        generator._ensure_dates(months)
        count = DateList.objects.filter(user=self.user, date__in=months).count()
        self.assertEqual(count, 2)

    def test_ensure_dates_skips_existing(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))
        months = [date(2025, 1, 1), date(2025, 2, 1)]
        generator._ensure_dates(months)
        count = DateList.objects.filter(user=self.user, date__in=months).count()
        self.assertEqual(count, 2)

    def test_ensure_planning_expense(self) -> None:
        generator = DateListGenerator(user=self.user, type_='expense')
        category = ExpenseCategory.objects.filter(user=self.user).first()
        if category:
            months = [date(2025, 1, 1)]
            generator._ensure_planning(months)
            count = Planning.objects.filter(
                user=self.user,
                planning_type='expense',
                date__in=months,
            ).count()
            self.assertGreaterEqual(count, 0)

    def test_ensure_planning_income(self) -> None:
        generator = DateListGenerator(user=self.user, type_='income')
        category = IncomeCategory.objects.filter(user=self.user).first()
        if category:
            months = [date(2025, 1, 1)]
            generator._ensure_planning(months)
            count = Planning.objects.filter(
                user=self.user,
                planning_type='income',
                date__in=months,
            ).count()
            self.assertGreaterEqual(count, 0)

    def test_ensure_planning_invalid_type(self) -> None:
        generator = DateListGenerator(user=self.user, type_='invalid')
        months = [date(2025, 1, 1)]
        generator._ensure_planning(months)
        count = Planning.objects.filter(user=self.user).count()
        self.assertEqual(count, 0)

    def test_ensure_planning_none_type(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        months = [date(2025, 1, 1)]
        generator._ensure_planning(months)
        count = Planning.objects.filter(user=self.user).count()
        self.assertEqual(count, 0)

    def test_run_with_datetime(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        test_datetime = timezone.make_aware(
            datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        )
        generator.run(test_datetime)
        count = DateList.objects.filter(user=self.user).count()
        self.assertGreater(count, 0)

    def test_run_with_queryset(self) -> None:
        generator = DateListGenerator(user=self.user, type_=None)
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))
        queryset: 'QuerySet[DateList]' = DateList.objects.filter(user=self.user)
        generator.run(queryset)
        count = DateList.objects.filter(user=self.user).count()
        self.assertGreater(count, 0)


class GenerateDateListTest(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_generate_date_list_with_datetime(self) -> None:
        test_datetime = timezone.make_aware(
            datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        )
        generate_date_list(test_datetime, self.user, None)
        count = DateList.objects.filter(user=self.user).count()
        self.assertGreater(count, 0)

    def test_generate_date_list_with_queryset(self) -> None:
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))
        queryset: 'QuerySet[DateList]' = DateList.objects.filter(user=self.user)
        generate_date_list(queryset, self.user, 'expense')
        count = DateList.objects.filter(user=self.user).count()
        self.assertGreater(count, 0)

    def test_generate_date_list_with_type(self) -> None:
        test_datetime = timezone.make_aware(
            datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        )
        generate_date_list(test_datetime, self.user, 'income')
        count = DateList.objects.filter(user=self.user).count()
        self.assertGreater(count, 0)
