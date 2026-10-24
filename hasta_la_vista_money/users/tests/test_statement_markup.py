from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    MerchantCategory,
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

    def test_categories_are_sorted_by_name(self) -> None:
        self._category('Аптека')
        recent = self._category('Яблоки')
        self._category('Книги')
        self.service.post(self._row(1).pk, self.user.pk, recent.pk)

        names = [c.name for c in self.service.categories(self.user, 'expense')]

        self.assertEqual(names, ['Аптека', 'Книги', 'Яблоки'])

    def test_manual_transaction_flags_one_row_as_duplicate(self) -> None:
        first = self._row(1, amount='54.00')
        second = self._row(2, amount='54.00')
        self._row(3, amount='178.00')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self._category('Оплата проезда'),
            type='expense',
            amount=Decimal('54.00'),
            date=datetime(
                2026,
                3,
                1,
                18,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        duplicates = self.service.probable_duplicates(self.upload)

        self.assertEqual(list(duplicates), [first.pk])
        self.assertEqual(duplicates[first.pk], 'Оплата проезда')
        self.assertNotIn(second.pk, duplicates)

    def test_imported_transaction_does_not_flag_row(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._row(1).pk, self.user.pk, category.pk)
        row = self._row(2)

        self.assertNotIn(row.pk, self.service.probable_duplicates(self.upload))

    def test_manual_transfer_flags_row_as_duplicate(self) -> None:
        row = self._row(1, amount='2231.00')
        other = Account.objects.create(
            user=self.user,
            name_account='Ozon',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=other,
            amount=Decimal('2231.00'),
            exchange_date=datetime(
                2026,
                3,
                1,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        duplicates = self.service.probable_duplicates(self.upload)

        self.assertEqual(duplicates, {row.pk: 'Перевод: РосДорБанк → Ozon'})

    def test_receipt_flags_row_as_duplicate(self) -> None:
        purchase = self._row(1, amount='312.50')
        refund = self._row(2, transaction_type='income', amount='99.90')
        self._row(3, amount='99.90')
        seller = Seller.objects.create(user=self.user, name_seller='Пятёрочка')
        for operation_type, total_sum in (
            (constants.RECEIPT_OPERATION_PURCHASE, '312.50'),
            (constants.RECEIPT_OPERATION_RETURN, '99.90'),
        ):
            Receipt.objects.create(
                user=self.user,
                account=self.account,
                seller=seller,
                operation_type=operation_type,
                total_sum=Decimal(total_sum),
                receipt_date=datetime(
                    2026,
                    3,
                    1,
                    15,
                    tzinfo=timezone.get_current_timezone(),
                ),
            )

        duplicates = self.service.probable_duplicates(self.upload)

        self.assertEqual(
            duplicates,
            {
                purchase.pk: 'Чек: Пятёрочка',
                refund.pk: 'Чек: Пятёрочка',
            },
        )


OWN_NUMBER = '40817810000000000001'


class StatementOwnTransferTest(StatementMarkupFixture):
    def setUp(self) -> None:
        super().setUp()
        self.other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
            account_number=OWN_NUMBER,
        )
        self.client.force_login(self.user)

    def _own_row(
        self,
        transaction_type: str = 'expense',
        counterparty: str = OWN_NUMBER,
        kind: str = 'own_c2c',
    ) -> BankStatementRow:
        row = self._row(1, transaction_type, kind)
        row.counterparty_account = counterparty
        row.save(update_fields=['counterparty_account'])
        return row

    def test_expense_row_transfers_to_account_found_by_number(self) -> None:
        row = self._own_row()

        self.service.post_transfer(row.pk, self.user.pk, None)

        row.refresh_from_db()
        self.account.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(self.other.balance, Decimal('600.00'))
        self.assertEqual(row.decision, BankStatementRow.Decision.TRANSFERRED)
        transfer = row.transfer
        if transfer is None:
            self.fail('row is not linked to a transfer')
        self.assertEqual(transfer.from_account, self.account)
        self.assertEqual(transfer.to_account, self.other)
        self.assertIsNone(row.transaction)

    def test_income_row_transfers_from_chosen_account(self) -> None:
        row = self._own_row('income')

        self.service.post_transfer(row.pk, self.user.pk, None)

        self.account.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1100.00'))
        self.assertEqual(self.other.balance, Decimal('400.00'))

    def test_chosen_account_receives_the_counterparty_number(self) -> None:
        number = '40817810000000000002'
        row = self._own_row(counterparty=number)
        self.other.account_number = None
        self.other.save(update_fields=['account_number'])

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, None)
        self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        self.other.refresh_from_db()
        self.assertEqual(self.other.account_number, number)

    def test_chosen_account_with_other_number_is_rejected(self) -> None:
        row = self._own_row(counterparty='40817810000000000002')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        self.assertEqual(TransferMoneyLog.objects.count(), 0)

    def test_number_of_foreign_account_is_rejected(self) -> None:
        number = '40817810000000000002'
        stranger = User.objects.create_user(username='stranger', password='x')
        Account.objects.create(
            user=stranger,
            name_account='Чужой',
            balance=Decimal('0.00'),
            currency='RUB',
            account_number=number,
        )
        row = self._own_row(counterparty=number)
        mine = Account.objects.create(
            user=self.user,
            name_account='Мой',
            balance=Decimal('0.00'),
            currency='RUB',
        )

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, mine.pk)

    def test_transfer_to_credit_card_is_a_repayment(self) -> None:
        Account.objects.filter(pk=self.other.pk).update(
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            limit_credit=Decimal('1000.00'),
            balance=Decimal('300.00'),
        )
        row = self._own_row()

        self.service.post_transfer(row.pk, self.user.pk, None)

        self.other.refresh_from_db()
        self.assertEqual(self.other.balance, Decimal('400.00'))

    def test_unknown_row_transfers_to_chosen_account(self) -> None:
        row = self._own_row(counterparty='', kind='unknown')

        self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.TRANSFERRED)

    def test_card_row_cannot_be_a_transfer(self) -> None:
        row = self._own_row(kind='card')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, self.other.pk)

    def test_same_account_is_rejected(self) -> None:
        row = self._own_row(counterparty='', kind='unknown')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_transfer(row.pk, self.user.pk, self.account.pk)

    def test_transfer_is_one_markup_audit_operation(self) -> None:
        row = self._own_row()
        AuditLog.objects.all().delete()

        self.service.post_transfer(row.pk, self.user.pk, None)

        logs = AuditLog.objects.all()
        self.assertTrue(logs.exists())
        self.assertEqual(
            set(logs.values_list('kind', flat=True)),
            {AuditOperationKind.STATEMENT_MARKUP},
        )
        self.assertEqual(logs.values('operation_id').distinct().count(), 1)

    def test_deleting_the_transfer_reopens_the_row(self) -> None:
        row = self._own_row()
        self.service.post_transfer(row.pk, self.user.pk, None)
        row.refresh_from_db()
        if row.transfer is None:
            self.fail('row is not linked to a transfer')

        ApplicationContainer().finance_account.transfer_service().delete_transfer(
            transfer_id=row.transfer.pk,
            user=self.user,
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)

    def test_page_preselects_account_found_by_number(self) -> None:
        self._own_row()

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertContains(
            response,
            f'<option value="{self.other.pk}" selected>Накопительный',
        )

    def test_card_row_has_no_transfer_button(self) -> None:
        row = self._row(1)

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertNotContains(response, f'name="account-{row.pk}"')

    def test_decide_transfer_closes_row(self) -> None:
        row = self._own_row()

        response = self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk],
            ),
            {'row': row.pk, f'account-{row.pk}': self.other.pk},
        )

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.TRANSFERRED)


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
                args=[self.upload.pk],
            ),
            {'row': row.pk, f'category-{row.pk}': category.pk},
        )

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)

    def test_decide_skip(self) -> None:
        row = self._row(1)

        self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk],
            ),
            {'row': row.pk, f'skip-{row.pk}': 'on'},
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.SKIPPED)

    def test_decide_applies_every_row_of_the_page_at_once(self) -> None:
        posted, skipped, untouched = self._row(1), self._row(2), self._row(3)
        category = self._category('Продукты')
        AuditLog.objects.all().delete()

        self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk],
            ),
            {
                'row': [posted.pk, skipped.pk, untouched.pk],
                f'category-{posted.pk}': category.pk,
                f'skip-{skipped.pk}': 'on',
                f'category-{skipped.pk}': category.pk,
                f'category-{untouched.pk}': '',
            },
        )

        decisions = dict(
            BankStatementRow.objects.values_list('pk', 'decision'),
        )
        self.assertEqual(
            decisions,
            {
                posted.pk: BankStatementRow.Decision.NEW,
                skipped.pk: BankStatementRow.Decision.SKIPPED,
                untouched.pk: BankStatementRow.Decision.AWAITING_MARKUP,
            },
        )
        logs = AuditLog.objects.all()
        self.assertEqual(logs.values('operation_id').distinct().count(), 1)

    def test_decide_refund_option_posts_cancel_row_to_returns(self) -> None:
        row = self._row(1, transaction_type='income', kind='cancel')

        self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk],
            ),
            {'row': row.pk, f'category-{row.pk}': 'refund'},
        )

        row.refresh_from_db()
        if row.transaction is None:
            self.fail('row is not linked to a movement')
        self.assertEqual(row.transaction.category.name, 'Возвраты')

    def test_decide_many_counts_conflicting_rows(self) -> None:
        good, bad = self._row(1), self._row(2)
        category = self._category('Продукты')

        result = self.service.decide_many(
            self.upload.pk,
            self.user.pk,
            {good.pk: ('post', category.pk), bad.pk: ('post', None)},
        )

        self.assertEqual(result, (1, 1))
        bad.refresh_from_db()
        self.assertEqual(
            bad.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_decide_ignores_rows_of_other_uploads(self) -> None:
        other_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='other.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        row = self._row(1)
        row.upload = other_upload
        row.save(update_fields=['upload'])

        self.client.post(
            reverse(
                'users:bank_statement_markup_decide',
                args=[self.upload.pk],
            ),
            {'row': row.pk, f'skip-{row.pk}': 'on'},
        )

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

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


class StatementMarkupCategoryModalTest(StatementMarkupFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)
        self.row = self._row(1, transaction_type='expense')
        self.url = reverse(
            'users:bank_statement_markup_category',
            args=[self.upload.pk, self.row.pk],
        )

    def test_modal_offers_parents_of_row_type_only(self) -> None:
        self._category('Еда')
        self._category('Зарплата', kind='income')

        response = self.client.get(self.url)

        self.assertContains(response, 'Еда')
        self.assertNotContains(response, 'Зарплата')

    def test_create_uses_row_type_and_selects_in_origin_row(self) -> None:
        parent = self._category('Еда')

        response = self.client.post(
            self.url,
            {'name': 'Кафе', 'parent_category': parent.pk, 'type': 'income'},
        )

        category = Category.objects.get(user=self.user, name='Кафе')
        self.assertEqual(category.type, 'expense')
        self.assertEqual(category.parent_category, parent)
        self.assertContains(response, f'value="{category.pk}" selected')
        self.assertContains(
            response,
            f'beforeend:#category-{self.row.pk}',
        )

    def test_invalid_form_keeps_modal_and_creates_nothing(self) -> None:
        self._category('Кафе')

        response = self.client.post(self.url, {'name': 'Кафе'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Category.objects.filter(name='Кафе').count(), 1)
        self.assertNotContains(response, 'hx-swap-oob')

    def test_close_returns_empty_body(self) -> None:
        response = self.client.get(f'{self.url}?close=1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'')

    def test_other_user_gets_404(self) -> None:
        other = User.objects.create_user(username='other', password='x')
        self.client.force_login(other)

        self.assertEqual(
            self.client.post(self.url, {'name': 'Х'}).status_code,
            404,
        )


class RememberedMerchantCategoryTest(StatementMarkupFixture):
    def _keyed(
        self,
        position: int,
        key: str = 'PYATEROCHKA',
        kind: str = 'card',
        transaction_type: str = 'expense',
    ) -> BankStatementRow:
        row = self._row(position, transaction_type, kind)
        row.merchant_key = key
        row.save(update_fields=['merchant_key'])
        return row

    def test_markup_remembers_last_category(self) -> None:
        first = self._category('Продукты')
        second = self._category('Хозтовары')

        self.service.post(self._keyed(1).pk, self.user.pk, first.pk)
        self.service.post(self._keyed(2).pk, self.user.pk, second.pk)

        memory = MerchantCategory.objects.get()
        self.assertEqual(memory.category, second)
        self.assertEqual(memory.merchant_key, 'PYATEROCHKA')

    def test_post_remembered_skips_probable_duplicates(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        row = self._keyed(2)
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type='expense',
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, tzinfo=timezone.get_current_timezone()),
        )

        result = self.service.post_remembered(self.upload.pk, self.user.pk)

        self.assertEqual(result, (0, 1))
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_probable_duplicate_is_marked_skip_by_default(self) -> None:
        category = self._category('Продукты')
        duplicate = self._row(1)
        fresh = self._row(2, amount='250.00')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type='expense',
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, tzinfo=timezone.get_current_timezone()),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertContains(response, f'name="skip-{duplicate.pk}" checked')
        self.assertContains(response, f'name="skip-{fresh.pk}">')

    def test_type_is_part_of_the_key(self) -> None:
        expense = self._category('Продукты')
        income = self._category('Кэшбэк', 'income')

        self.service.post(self._keyed(1).pk, self.user.pk, expense.pk)
        self.service.post(
            self._keyed(2, transaction_type='income').pk,
            self.user.pk,
            income.pk,
        )

        self.assertEqual(MerchantCategory.objects.count(), 2)

    def test_c2c_and_skip_remember_nothing(self) -> None:
        category = self._category('Подарки')

        self.service.post(
            self._keyed(1, key='', kind='c2c').pk,
            self.user.pk,
            category.pk,
        )
        self.service.skip(self._keyed(2).pk, self.user.pk)

        self.assertFalse(MerchantCategory.objects.exists())

    def test_remembered_rows_map_pending_rows_to_category(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        known = self._keyed(2)
        self._keyed(3, key='OTHER')

        self.assertEqual(
            self.service.remembered_categories(self.upload),
            {known.pk: category.pk},
        )

    def test_post_remembered_posts_known_rows_as_one_operation(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        known = [self._keyed(2), self._keyed(3)]
        unknown = self._keyed(4, key='OTHER')
        AuditLog.objects.all().delete()

        posted = self.service.post_remembered(self.upload.pk, self.user.pk)

        self.assertEqual(posted, (2, 0))
        for row in known:
            row.refresh_from_db()
            self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
            if row.transaction is None:
                self.fail('row is not linked to a movement')
            self.assertEqual(row.transaction.category, category)
        unknown.refresh_from_db()
        self.assertEqual(
            unknown.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(
            AuditLog.objects.values('operation_id').distinct().count(),
            1,
        )

    def test_post_remembered_skips_conflicting_rows(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        row = self._keyed(2)
        self.upload.expires_at = timezone.now()
        self.upload.save(update_fields=['expires_at'])

        result = self.service.post_remembered(self.upload.pk, self.user.pk)

        self.assertEqual(result, (0, 1))
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_page_preselects_remembered_category(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        self._keyed(2)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertContains(response, f'value="{category.pk}" selected')
        self.assertContains(response, 'Провести все с подставленной')

    def test_post_remembered_view_posts_and_redirects(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        row = self._keyed(2)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                'users:bank_statement_markup_post_remembered',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)

    def test_post_remembered_view_honours_skip_marks(self) -> None:
        category = self._category('Продукты')
        self.service.post(self._keyed(1).pk, self.user.pk, category.pk)
        skipped, posted = self._keyed(2), self._keyed(3)
        self.client.force_login(self.user)

        self.client.post(
            reverse(
                'users:bank_statement_markup_post_remembered',
                args=[self.upload.pk],
            ),
            {'row': [skipped.pk, posted.pk], f'skip-{skipped.pk}': 'on'},
        )

        skipped.refresh_from_db()
        posted.refresh_from_db()
        self.assertEqual(skipped.decision, BankStatementRow.Decision.SKIPPED)
        self.assertEqual(posted.decision, BankStatementRow.Decision.NEW)

    def test_other_user_cannot_post_remembered(self) -> None:
        other = User.objects.create_user(username='other', password='x')
        self.client.force_login(other)

        response = self.client.post(
            reverse(
                'users:bank_statement_markup_post_remembered',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 404)


class StatementMarkupRemindersTest(StatementMarkupFixture):
    def setUp(self) -> None:
        super().setUp()
        self.upload.statement_closing_balance = Decimal('880.00')
        self.upload.save()

    def test_discrepancy_appears_when_no_rows_await_markup(self) -> None:
        first = self._row(1)
        second = self._row(2)

        self.service.post(first.pk, self.user.pk, self._category('Еда').pk)
        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.balance_discrepancy)

        self.service.skip(second.pk, self.user.pk)
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.account_balance_after, Decimal('900.00'))
        self.assertEqual(self.upload.balance_discrepancy, Decimal('-20.00'))

    def test_discrepancy_needs_statement_closing_balance(self) -> None:
        self.upload.statement_closing_balance = None
        self.upload.save()
        row = self._row(1)

        self.service.skip(row.pk, self.user.pk)

        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.balance_discrepancy)

    def test_awaiting_rows_expire_with_the_upload(self) -> None:
        row = self._row(1)
        self.assertGreater(
            self.upload.expires_at - timezone.now(),
            timedelta(days=constants.STATEMENT_RETENTION_DAYS - 1),
        )

        container = ApplicationContainer()
        cleaned = (
            container.users.bank_statement_retention_service().cleanup_expired(
                self.upload.expires_at,
            )
        )

        self.assertEqual(cleaned, 1)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)

    def test_pending_count_ignores_other_users_and_expired(self) -> None:
        self._row(1)
        self._row(2)
        expired = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='old.pdf',
            expires_at=timezone.now() - timedelta(days=1),
        )
        BankStatementRow.objects.create(
            upload=expired,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        newer = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='newer.pdf',
            expires_at=self.upload.expires_at,
        )
        BankStatementRow.objects.create(
            upload=newer,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        count, upload_id = self.service.pending_summary(self.user.pk)

        self.assertEqual((count, upload_id), (1, newer.pk))
        self.assertEqual(self.service.pending_summary(999999), (0, None))


class DashboardMarkupReminderTest(StatementMarkupFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)

    def test_banner_links_to_markup_screen(self) -> None:
        self._row(1)
        self._row(2)

        response = self.client.get(reverse('users:dashboard'))

        self.assertContains(response, '2 строки ждут разметки')
        self.assertContains(
            response,
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

    def test_banner_uses_russian_plural_forms(self) -> None:
        for count, text in ((1, '1 строка ждёт'), (3, '3 строки ждут')):
            BankStatementRow.objects.all().delete()
            for position in range(count):
                self._row(position)

            response = self.client.get(reverse('users:dashboard'))

            self.assertContains(response, f'{text} разметки')

    def test_no_banner_without_pending_rows(self) -> None:
        response = self.client.get(reverse('users:dashboard'))

        self.assertNotContains(response, 'ждут разметки')


class StatementBulkMarkupTest(StatementMarkupFixture):
    def test_posts_all_rows_in_one_audit_operation(self) -> None:
        rows = [self._row(1), self._row(2)]
        category = self._category('Продукты')
        AuditLog.objects.all().delete()

        self.service.post_many(
            [row.pk for row in rows],
            self.user.pk,
            category.pk,
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('800.00'))
        self.assertEqual(
            Transaction.objects.filter(category=category).count(),
            2,
        )
        logs = AuditLog.objects.all()
        self.assertEqual(
            set(logs.values_list('kind', flat=True)),
            {AuditOperationKind.STATEMENT_MARKUP},
        )
        self.assertEqual(logs.values('operation_id').distinct().count(), 1)

    def test_mixed_directions_are_rejected_without_changes(self) -> None:
        rows = [self._row(1), self._row(2, transaction_type='income')]
        category = self._category('Продукты')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many(
                [row.pk for row in rows],
                self.user.pk,
                category.pk,
            )

        self.assertFalse(Transaction.objects.exists())

    def test_own_transfer_row_is_rejected(self) -> None:
        rows = [self._row(1), self._row(2, kind='own_c2c')]
        category = self._category('Продукты')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many(
                [row.pk for row in rows],
                self.user.pk,
                category.pk,
            )

        self.assertFalse(Transaction.objects.exists())

    def test_already_decided_row_rolls_everything_back(self) -> None:
        first, second = self._row(1), self._row(2)
        self.service.skip(second.pk, self.user.pk)
        category = self._category('Продукты')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many(
                [first.pk, second.pk],
                self.user.pk,
                category.pk,
            )

        first.refresh_from_db()
        self.assertEqual(
            first.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_category_of_other_direction_is_rejected(self) -> None:
        row = self._row(1)
        category = self._category('Зарплата', 'income')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many([row.pk], self.user.pk, category.pk)

    def test_empty_selection_is_rejected(self) -> None:
        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many([], self.user.pk, None)

    def test_foreign_row_is_rejected(self) -> None:
        other = User.objects.create_user(username='other', password='x')
        row = self._row(1)
        category = self._category('Продукты')

        with self.assertRaises(StatementMarkupConflictError):
            self.service.post_many([row.pk], other.pk, category.pk)

    def test_bulk_view_posts_selected_rows(self) -> None:
        self.client.force_login(self.user)
        rows = [self._row(1), self._row(2)]
        category = self._category('Продукты')

        response = self.client.post(
            reverse('users:bank_statement_markup_bulk', args=[self.upload.pk]),
            {'rows': [row.pk for row in rows], 'category': category.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            2,
        )

    def test_bulk_view_honours_skip_marks(self) -> None:
        self.client.force_login(self.user)
        skipped, posted = self._row(1), self._row(2)
        category = self._category('Продукты')

        self.client.post(
            reverse('users:bank_statement_markup_bulk', args=[self.upload.pk]),
            {
                'row': [skipped.pk, posted.pk],
                'rows': [skipped.pk, posted.pk],
                'category': category.pk,
                f'skip-{skipped.pk}': 'on',
            },
        )

        skipped.refresh_from_db()
        posted.refresh_from_db()
        self.assertEqual(skipped.decision, BankStatementRow.Decision.SKIPPED)
        self.assertEqual(posted.decision, BankStatementRow.Decision.NEW)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_every_page_action_submits_the_skip_marks(self) -> None:
        self.client.force_login(self.user)
        row = self._row(1)

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        bulk_url = reverse(
            'users:bank_statement_markup_bulk',
            args=[self.upload.pk],
        )
        self.assertContains(response, 'id="markup-form"')
        self.assertContains(response, f'formaction="{bulk_url}"')
        self.assertNotContains(response, 'form="bulk-form"')
        self.assertContains(response, f'name="skip-{row.pk}"')

    def test_bulk_view_without_selection_changes_nothing(self) -> None:
        self.client.force_login(self.user)
        row = self._row(1)

        self.client.post(
            reverse('users:bank_statement_markup_bulk', args=[self.upload.pk]),
            {'category': self._category('Продукты').pk},
        )

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_page_has_checkboxes_but_not_for_own_transfers(self) -> None:
        self.client.force_login(self.user)
        card = self._row(1)
        own = self._row(2, kind='own_c2c')

        response = self.client.get(
            reverse('users:bank_statement_markup', args=[self.upload.pk]),
        )

        self.assertContains(response, f'name="rows" value="{card.pk}"')
        self.assertNotContains(response, f'name="rows" value="{own.pk}"')
