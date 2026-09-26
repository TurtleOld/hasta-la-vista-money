"""Tests for the credit-cards tab of the detailed statistics page.

The fixture mirrors a real Sberbank card checked against a bank statement
on 26.09.2026: limit 100 000, account balance 81 529.43, total debt
18 470.57 (18 385.44 for 08.2026 purchases + 85.13 for 09.2026), mandatory
payment 551.56 due 30.09.2026. Part of the card's debt existed before the
user started tracking it, so the movement history alone does not add up
to the bank's debt.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    CreditCardDataDict,
    StatisticsFilters,
    get_user_detailed_statistics,
)

User = get_user_model()

TODAY = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class CreditCardStatisticsTest(TestCase):
    """Credit-card figures on the statistics page match the bank."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            username='carduser',
            password='testpass123',  # nosec B106: test-only password
        )
        sberbank = Bank.objects.get(code='SBERBANK')
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитная СберКарта',
            balance=Decimal('81529.43'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            bank=sberbank,
        )
        self.debit = Account.objects.create(
            user=self.user,
            name_account='Дебетовая карта',
            balance=Decimal('1000.00'),
            currency='RUB',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            bank=sberbank,
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Покупки',
            type=TransactionType.EXPENSE,
        )
        # 4 000 of debt predates tracking; the 10.05 repayment covers it
        # and the April purchase.
        self._purchase('1000.00', datetime(2026, 4, 15, 12, 0, tzinfo=UTC))
        self._repay('5000.00', datetime(2026, 5, 10, 12, 0, tzinfo=UTC))
        self._purchase('199.00', datetime(2026, 7, 9, 7, 6, tzinfo=UTC))
        self._repay('199.00', datetime(2026, 8, 1, 9, 5, tzinfo=UTC))
        self._purchase('10934.58', datetime(2026, 8, 2, 15, 13, tzinfo=UTC))
        self._purchase('7450.86', datetime(2026, 8, 2, 15, 14, tzinfo=UTC))
        self._purchase('85.13', datetime(2026, 9, 1, 0, 15, tzinfo=UTC))

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _purchase(self, amount: str, when: datetime) -> None:
        Transaction.objects.create(
            user=self.user,
            account=self.card,
            category=self.category,
            amount=Decimal(amount),
            date=when,
            type=TransactionType.EXPENSE,
        )

    def _repay(self, amount: str, when: datetime) -> None:
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal(amount),
            exchange_date=when,
        )

    def _statistics(
        self,
        today: datetime = TODAY,
        stats_filter: StatisticsFilters | None = None,
    ) -> dict[str, Any]:
        with patch('django.utils.timezone.now', return_value=today):
            stats = get_user_detailed_statistics(
                self.user,
                container=ApplicationContainer(),
                stats_filter=stats_filter or StatisticsFilters(),
            )
        return dict(stats)

    def _card_data(self, today: datetime = TODAY) -> CreditCardDataDict:
        cards: list[CreditCardDataDict] = self._statistics(today)[
            'credit_cards_data'
        ]
        self.assertEqual(len(cards), 1)
        return cards[0]

    def test_debt_is_limit_minus_account_balance(self) -> None:
        stats = self._statistics()
        card = stats['credit_cards_data'][0]

        self.assertEqual(card['debt_now'], Decimal('18470.57'))
        self.assertEqual(card['limit_left'], Decimal('81529.43'))
        self.assertEqual(
            stats['credit_cards_summary']['total_remaining_debt'],
            Decimal('18470.57'),
        )

    def test_payment_schedule_matches_bank_periods(self) -> None:
        schedule = {
            item['month']: item
            for item in self._card_data()['payment_schedule']
        }

        self.assertTrue(schedule['07.2026']['is_paid'])
        self.assertEqual(schedule['07.2026']['remaining_debt'], Decimal(0))
        self.assertEqual(
            schedule['08.2026']['remaining_debt'],
            Decimal('18385.44'),
        )
        self.assertEqual(schedule['08.2026']['payment_due'], '30.11.2026')
        self.assertEqual(
            schedule['09.2026']['remaining_debt'],
            Decimal('85.13'),
        )
        self.assertEqual(schedule['09.2026']['payment_due'], '31.12.2026')

    def test_grace_summary_mirrors_bank_app(self) -> None:
        summary = self._card_data()['grace_summary']

        self.assertEqual(summary['nearest_due_date'], date(2026, 11, 30))
        self.assertEqual(summary['nearest_due_amount'], Decimal('18385.44'))
        self.assertEqual(summary['current_period_end'], date(2026, 9, 30))
        self.assertEqual(summary['current_grace_end'], date(2026, 12, 31))
        self.assertEqual(summary['current_purchases'], Decimal('85.13'))
        self.assertEqual(summary['mandatory_payment'], Decimal('551.56'))
        self.assertEqual(
            summary['mandatory_payment_due'],
            date(2026, 9, 30),
        )

    def test_repayment_in_current_month_keeps_period_purchases(self) -> None:
        self._repay('50.00', datetime(2026, 9, 20, 12, 0, tzinfo=UTC))
        self.card.balance = Decimal('81579.43')
        self.card.save(update_fields=['balance'])

        summary = self._card_data()['grace_summary']

        self.assertEqual(summary['current_purchases'], Decimal('85.13'))
        self.assertEqual(summary['mandatory_payment'], Decimal('551.56'))

    def test_overdue_period_hides_mandatory_payment(self) -> None:
        summary = self._card_data(
            datetime(2026, 12, 5, 12, 0, tzinfo=UTC),
        )['grace_summary']

        self.assertEqual(summary['nearest_due_date'], date(2026, 11, 30))
        self.assertIsNone(summary['mandatory_payment'])
        self.assertTrue(summary['mandatory_payment_unknown'])

    def test_utilization_is_month_end_debt_to_limit(self) -> None:
        chart = self._card_data()['utilization_chart']
        utilization = dict(zip(chart['labels'], chart['values'], strict=True))

        self.assertEqual(utilization['07.2026'], 0.2)
        self.assertEqual(utilization['08.2026'], 18.39)
        self.assertEqual(utilization['09.2026'], 18.47)

    def test_schedule_consistent_with_debt_has_no_warning(self) -> None:
        card = self._card_data()

        self.assertFalse(card['schedule_mismatch'])

    def test_schedule_short_of_debt_warns_about_missing_data(self) -> None:
        self.card.balance = Decimal('70000.00')
        self.card.save(update_fields=['balance'])

        card = self._card_data()

        self.assertTrue(card['schedule_mismatch'])
        self.assertEqual(card['schedule_debt'], Decimal('19669.57'))

    def _page(self) -> HttpResponse:
        self.client.force_login(self.user)
        with patch('django.utils.timezone.now', return_value=TODAY):
            response = self.client.get(reverse('users:statistics'))
        self.assertEqual(response.status_code, 200)
        return cast('HttpResponse', response)

    def test_page_shows_grace_block_like_bank(self) -> None:
        response = self._page()

        self.assertContains(response, 'Долг: 18 470.57 RUB')
        self.assertContains(response, 'До 30.11.2026 осталось внести')
        self.assertContains(response, '18 385.44 RUB')
        self.assertContains(
            response,
            'На всё, что купите до 30.09.2026, действует беспроцентный '
            'период до 31.12.2026',
        )
        self.assertContains(response, 'Обязательный платёж до 30.09.2026')
        self.assertContains(response, '551.56 RUB')
        self.assertNotContains(response, 'Если платить только минимум')
        self.assertNotContains(response, 'Долг за месяц')
        self.assertNotContains(response, 'не совпадает с задолженностью')

    def test_page_warns_when_schedule_short_of_debt(self) -> None:
        self.card.balance = Decimal('70000.00')
        self.card.save(update_fields=['balance'])

        response = self._page()

        self.assertContains(response, 'не совпадает с задолженностью')

    def test_utilization_counts_refund_receipt_as_balance_increase(
        self,
    ) -> None:
        Receipt.objects.create(
            user=self.user,
            account=self.card,
            receipt_date=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
            operation_type=3,
            total_sum=Decimal('100.00'),
        )
        self.card.balance = Decimal('81629.43')
        self.card.save(update_fields=['balance'])

        chart = self._card_data()['utilization_chart']
        utilization = dict(zip(chart['labels'], chart['values'], strict=True))

        self.assertEqual(utilization['08.2026'], 18.39)

    def test_past_period_filter_does_not_warn_about_mismatch(self) -> None:
        stats = self._statistics(
            stats_filter=StatisticsFilters(
                period='range',
                date_from=date(2026, 4, 1),
                date_to=date(2026, 8, 31),
            ),
        )

        self.assertFalse(stats['credit_cards_data'][0]['schedule_mismatch'])

    def test_card_without_limit_does_not_warn_about_mismatch(self) -> None:
        self.card.limit_credit = None
        self.card.save(update_fields=['limit_credit'])

        self.assertFalse(self._card_data()['schedule_mismatch'])
