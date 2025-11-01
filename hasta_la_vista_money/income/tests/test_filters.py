from typing import ClassVar

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.filters import IncomeFilter
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeFilterTest(TestCase):
    """
    Test cases for the IncomeFilter.
    """

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)

    def test_income_filter(self) -> None:
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_income_filter_with_data(self) -> None:
        filter_instance = IncomeFilter(
            data={
                'category': self.income_type.pk,
                'account': self.account.pk,
            },
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_income_filter_property_qs(self) -> None:
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        queryset = filter_instance.qs
        self.assertIsNotNone(queryset)
        self.assertTrue(hasattr(queryset, 'values'))

    def test_income_filter_init(self) -> None:
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertEqual(filter_instance.user, self.user)
