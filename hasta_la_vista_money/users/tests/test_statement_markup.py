from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)


class StatementMarkupFixture(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='rosdorbank.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.service = ApplicationContainer().users.statement_markup_service()

    def _row(
        self,
        position: int,
        transaction_type: str = 'expense',
        kind: str = 'card',
        amount: str = '100.00',
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=transaction_type,
            transaction_date=datetime(
                2026,
                3,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            amount=Decimal(amount),
            description='ПЯТЁРОЧКА',
            source_ref=f'{position}-01.03.2026',
            source_row_position=position,
            kind=kind,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def _category(self, name: str, kind: str = 'expense') -> Category:
        return Category.objects.create(user=self.user, name=name, type=kind)


class StatementMarkupTest(StatementMarkupFixture):
    def test_post_expense_moves_balance_and_links_row(self) -> None:
        row = self._row(1)
        category = self._category('Продукты')

        self.service.post(row.pk, self.user.pk, category.pk)

        row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        movement = row.transaction
        if movement is None:
            self.fail('row is not linked to a movement')
        self.assertEqual(movement.category, category)
        self.assertEqual(movement.source_ref, '1-01.03.2026')
        local = timezone.localtime(movement.date)
        self.assertEqual(
            local.date(),
            datetime(2026, 3, 1, tzinfo=timezone.get_current_timezone()).date(),
        )
        self.assertNotEqual((local.hour, local.minute), (0, 0))

    def test_post_income_adds_to_balance(self) -> None:
        row = self._row(1, transaction_type='income')
        category = self._category('Зарплата', 'income')

        self.service.post(row.pk, self.user.pk, category.pk)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1100.00'))

    def test_skip_does_not_touch_balance(self) -> None:
        row = self._row(1)

        self.service.skip(row.pk, self.user.pk)

        row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.SKIPPED)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())

    def test_cancel_row_defaults_to_returns_category(self) -> None:
        row = self._row(1, transaction_type='income', kind='cancel')

        self.service.post(row.pk, self.user.pk, None)

        row.refresh_from_db()
        movement = row.transaction
        if movement is None:
            self.fail('row is not linked to a movement')
        self.assertEqual(movement.category.name, 'Возвраты')
        self.assertEqual(movement.category.type, 'income')

    def test_deposit_and_archived_accounts_are_rejected(self) -> None:
        row = self._row(1)
        category = self._category('Продукты')
        for change in (
            {'type_account': constants.ACCOUNT_TYPE_DEPOSIT},
            {'archived_at': timezone.now()},
        ):
            Account.objects.filter(pk=self.account.pk).update(**change)

            with self.assertRaises(StatementMarkupConflictError):
                self.service.post(row.pk, self.user.pk, category.pk)

            Account.objects.filter(pk=self.account.pk).update(
                type_account=constants.ACCOUNT_TYPE_CASH,
                archived_at=None,
            )
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_income_on_credit_card_is_rejected(self) -> None:
        Account.objects.filter(pk=self.account.pk).update(
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
        )
        row = self._row(1, transaction_type='income')
        category = self._category('Зарплата', 'income')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post(row.pk, self.user.pk, category.pk)

    def test_expired_upload_is_rejected(self) -> None:
        row = self._row(1)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now(),
        )

        with self.assertRaises(StatementMarkupConflictError):
            self.service.skip(row.pk, self.user.pk)

    def test_regular_row_requires_category(self) -> None:
        row = self._row(1)

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post(row.pk, self.user.pk, None)

    def test_category_of_other_type_is_rejected(self) -> None:
        row = self._row(1)
        category = self._category('Зарплата', 'income')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post(row.pk, self.user.pk, category.pk)

    def test_decided_row_is_not_posted_twice(self) -> None:
        row = self._row(1)
        category = self._category('Продукты')
        self.service.post(row.pk, self.user.pk, category.pk)

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post(row.pk, self.user.pk, category.pk)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_post_is_one_markup_audit_operation(self) -> None:
        row = self._row(1)
        category = self._category('Продукты')
        AuditLog.objects.all().delete()

        self.service.post(row.pk, self.user.pk, category.pk)

        logs = AuditLog.objects.all()
        self.assertTrue(logs.exists())
        self.assertEqual(
            set(logs.values_list('kind', flat=True)),
            {AuditOperationKind.STATEMENT_MARKUP},
        )
        self.assertEqual(logs.values('operation_id').distinct().count(), 1)

    def test_upload_completes_when_all_rows_decided(self) -> None:
        first = self._row(1)
        second = self._row(2)
        category = self._category('Продукты')

        self.service.post(first.pk, self.user.pk, category.pk)
        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.service.skip(second.pk, self.user.pk)

        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED,
        )

    def test_recent_categories_come_first(self) -> None:
        old = self._category('Аптека')
        recent = self._category('Яблоки')
        self._category('Книги')
        row = self._row(1)
        self.service.post(row.pk, self.user.pk, recent.pk)

        names = [c.name for c in self.service.categories(self.user, 'expense')]

        self.assertEqual(names[0], 'Яблоки')
        self.assertEqual(names[1:], ['Аптека', 'Книги'])
        self.assertNotIn(old.name, names[:1])


class StatementMarkupViewTest(StatementMarkupFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)

    def test_page_lists_rows_awaiting_markup(self) -> None:
        self._row(1)
        self._row(2, transaction_type='income')

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ПЯТЁРОЧКА', count=2)

    def test_other_user_gets_404(self) -> None:
        other = User.objects.create_user(username='other', password='x')
        self.client.force_login(other)

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertEqual(response.status_code, 404)

    def test_decide_post_posts_row(self) -> None:
        row = self._row(1)
        category = self._category('Продукты')

        response = self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk, row.pk],
            ),
            {'decision': 'post', 'category': category.pk},
        )

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)

    def test_decide_skip(self) -> None:
        row = self._row(1)

        self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk, row.pk],
            ),
            {'decision': 'skip'},
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.SKIPPED)

    def test_status_links_to_markup_screen(self) -> None:
        self._row(1)

        response = self.client.get(
            reverse(
                'users:bank_statement_upload_status',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(
            response.json()['reconciliation_url'],
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

    def test_history_links_to_markup_screen(self) -> None:
        self._row(1)

        response = self.client.get(reverse('users:bank_statement_upload'))

        self.assertContains(
            response,
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )
