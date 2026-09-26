"""View-level tests for the credit-card income ban and reminders."""

from datetime import UTC, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


class CreditCardIncomeBanViewTest(TestCase):
    """The income form rejects a credit card with a transfer link."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='banuser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.client.force_login(self.user)

    def test_create_income_on_credit_card_shows_transfer_link(self) -> None:
        response = self.client.post(
            reverse('finances_create'),
            {
                'operation_type': 'income',
                'category': self.income_category.pk,
                'account': self.card.pk,
                'date': '2026-04-01T12:00',
                'amount': '199.00',
            },
            follow=True,
        )

        self.assertContains(response, 'На кредитную карту нельзя внести доход')
        self.assertContains(response, 'Сделать перевод')
        self.assertContains(response, f'to_account={self.card.pk}')
        self.assertFalse(
            Transaction.objects.filter(account=self.card).exists(),
        )
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))


class PendingTransferViewTest(TestCase):
    """The card page shows reminders and conducts repayments."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='pendinguser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.debit = Account.objects.create(
            user=self.user,
            name_account='Дебет',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.card,
            pdf_file='bank_statements/pending.pdf',
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=0,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
            amount=Decimal('199.00'),
            description='Перевод на карту',
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.client.force_login(self.user)

    def test_card_page_shows_pending_repayment(self) -> None:
        response = self.client.get(reverse('finance_account:list'))

        self.assertContains(response, 'Непроведённые погашения из выписки')
        self.assertContains(response, '199')
        self.assertContains(response, 'Сделать перевод')
        self.assertContains(response, 'Не погашение')

    def test_transfer_form_prefilled_from_reminder(self) -> None:
        response = self.client.get(
            reverse('finance_account:transfer_money'),
            {
                'to_account': str(self.card.pk),
                'amount': '199.00',
                'date': '2026-02-09',
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form.fields['to_account'].initial, self.card)
        self.assertEqual(form.fields['amount'].initial, Decimal('199.00'))
        self.assertIsNotNone(form.fields['exchange_date'].initial)

    def test_transfer_to_card_closes_reminder(self) -> None:
        self.client.post(
            reverse('finance_account:transfer_money'),
            {
                'from_account': self.debit.pk,
                'to_account': self.card.pk,
                'amount': '199.00',
                'exchange_date': '2026-02-09T12:00',
                'notes': '',
            },
        )

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertIsNotNone(self.row.transfer_id)

    def test_dismiss_reminder_creates_no_movement(self) -> None:
        self.client.post(
            reverse(
                'users:bank_statement_pending_transfer_dismiss',
                args=[self.upload.pk, self.row.pk],
            ),
        )

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NOT_A_PAYMENT,
        )
        self.assertFalse(
            Transaction.objects.filter(account=self.card).exists(),
        )
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))
