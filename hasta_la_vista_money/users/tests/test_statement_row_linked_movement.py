"""Movements linked to a statement row: guarded edits, reset on delete."""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.commands import (
    UpdateTransactionCommand,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)


class StatementRowLinkedMovementTest(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()
        container = ApplicationContainer()
        self.transaction_service = container.transactions.transaction_service()
        self.transfer_service = container.finance_account.transfer_service()
        self.account = AccountFactory(
            user=self.user,
            balance=Decimal('1000.00'),
        )
        self.other_account = AccountFactory(
            user=self.user,
            balance=Decimal('500.00'),
            currency=self.account.currency,
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.expense = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal('100.00'),
            date=datetime(2026, 4, 1, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

    def _row(self, **kwargs: object) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            decision=BankStatementRow.Decision.LINKED,
            decided_at=datetime(2026, 4, 2, tzinfo=UTC),
            **kwargs,
        )

    def _update(
        self,
        *,
        amount: Decimal = Decimal('100.00'),
        account: Account | None = None,
        type_value: str = TransactionType.EXPENSE,
        category: Category | None = None,
        transaction_date: date = date(2026, 4, 5),
    ) -> None:
        self.transaction_service.update_transaction(
            UpdateTransactionCommand(
                user=self.user,
                transaction_obj=self.expense,
                account=account or self.account,
                category=category
                or (
                    self.income_category
                    if type_value == TransactionType.INCOME
                    else self.category
                ),
                amount=amount,
                transaction_date=transaction_date,
                type_value=type_value,
            ),
        )

    def _assert_pending(self, row: BankStatementRow) -> None:
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction)
        self.assertIsNone(row.transfer)
        self.assertIsNone(row.decided_at)

    def test_delete_transaction_returns_row_to_pending(self) -> None:
        row = self._row(transaction=self.expense)

        self.transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=self.expense,
        )

        self._assert_pending(row)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1100.00'))

    def test_delete_transfer_returns_row_to_pending(self) -> None:
        transfer = self.transfer_service.transfer_money(
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )
        row = self._row(transfer=transfer)

        self.transfer_service.delete_transfer(
            transfer_id=transfer.pk,
            user=self.user,
        )

        self._assert_pending(row)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_delete_candidate_keeps_row_decision(self) -> None:
        row = BankStatementRow.objects.create(
            upload=self.upload,
            candidate=self.expense,
        )

        self.transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=self.expense,
        )

        row.refresh_from_db()
        self.assertIsNone(row.candidate)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)

    def test_linked_transaction_rejects_amount_change(self) -> None:
        self._row(transaction=self.expense)
        with self.assertRaises(ValidationError):
            self._update(amount=Decimal('150.00'))
        self._assert_unchanged()

    def test_linked_transaction_rejects_account_change(self) -> None:
        self._row(transaction=self.expense)
        with self.assertRaises(ValidationError):
            self._update(account=self.other_account)
        self._assert_unchanged()

    def test_linked_transaction_rejects_direction_change(self) -> None:
        self._row(transaction=self.expense)
        with self.assertRaises(ValidationError):
            self._update(type_value=TransactionType.INCOME)
        self._assert_unchanged()

    def test_linked_transaction_allows_category_and_date_change(self) -> None:
        row = self._row(transaction=self.expense)
        other_category = Category.objects.create(
            user=self.user,
            name='Кафе',
            type=TransactionType.EXPENSE,
        )

        self._update(
            category=other_category,
            transaction_date=date(2026, 4, 9),
        )

        self.expense.refresh_from_db()
        self.assertEqual(self.expense.category, other_category)
        self.assertEqual(
            timezone.localtime(self.expense.date).date(),
            date(2026, 4, 9),
        )
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)

    def test_unlinked_transaction_amount_change_allowed(self) -> None:
        self._update(amount=Decimal('150.00'))
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.amount, Decimal('150.00'))

    def test_web_update_of_linked_transaction_amount_is_refused(self) -> None:
        self._row(transaction=self.expense)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                'finance_account:transaction_change',
                kwargs={'pk': self.expense.pk},
            ),
            {
                'type': TransactionType.EXPENSE,
                'category': self.category.pk,
                'account': self.account.pk,
                'date': '2026-04-05T10:00',
                'amount': '150.00',
            },
        )

        self.assertContains(response, 'связанной со строкой банковской выписки')
        self._assert_unchanged()

    def test_web_delete_of_linked_transaction_releases_row(self) -> None:
        row = self._row(transaction=self.expense)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                'finance_account:transaction_delete',
                kwargs={'pk': self.expense.pk},
            ),
        )

        self.assertEqual(response.status_code, 302)
        self._assert_pending(row)

    def _assert_unchanged(self) -> None:
        self.expense.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.expense.amount, Decimal('100.00'))
        self.assertEqual(self.expense.account, self.account)
        self.assertEqual(self.expense.type, TransactionType.EXPENSE)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
