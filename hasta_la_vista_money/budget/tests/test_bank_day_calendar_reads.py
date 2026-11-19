"""Budget actuals read the explicit bank day of a movement."""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import TestCase, override_settings

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

PAGO_PAGO = 'Pacific/Pago_Pago'


@override_settings(TIME_ZONE=PAGO_PAGO)
class BudgetBankDayReadTest(TestCase):
    """Month actuals count a movement in its bank month."""

    def test_month_actuals_use_the_bank_day(self) -> None:
        user = User.objects.create_user(username='budget-bank-day')
        account = Account.objects.create(
            user=user,
            name_account='Карта',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        category = Category.objects.create(
            user=user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=user,
            account=account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 1),
        )
        service = ApplicationContainer().budget.budget_service()

        overview = service.aggregate_budget_limit_overview(
            user=user,
            months=[date(2026, 3, 1)],
            expense_categories=[category],
            currency='RUB',
        )

        self.assertEqual(
            overview['monthly_limits'][0]['fact'],
            Decimal('100.00'),
        )
