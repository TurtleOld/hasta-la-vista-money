"""Tests for finance account views."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.core.handlers.wsgi import WSGIRequest
from django.test import RequestFactory, TestCase
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEPOSIT,
)
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.tests.helpers import (
    setup_container_for_request,
)
from hasta_la_vista_money.finance_account.views import (
    AccountCreateView,
    AccountView,
    ChangeAccountView,
    DeleteAccountView,
    FinancesFilter,
    TransferMoneyAccountView,
    _day_label,
    _finances_categories,
    _finances_transactions,
    _group_finances_by_day,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.repositories import ProductCategoryRepository
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.users.views import AuthRequest


class TestAccountView(TestCase):
    """Test cases for AccountView."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'categories.yaml',
        'transactions.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(id=1)
        self.factory = RequestFactory()

    def test_account_view_get_context_data(self) -> None:
        """Test AccountView get_context_data method."""
        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('finance_account', response.context)
        self.assertIn('add_account_form', response.context)
        self.assertIn('transfer_money_form', response.context)
        self.assertIn('transfer_money_log', response.context)
        self.assertIn('sum_all_accounts', response.context)
        self.assertIn('sum_all_accounts_in_group', response.context)
        self.assertIn('credit_balances_in_group', response.context)
        self.assertIn('deposit_balances_in_group', response.context)

    def test_account_view_separates_summary_balances_by_account_type(
        self,
    ) -> None:
        AccountFactory(
            user=self.user,
            type_account=constants.ACCOUNT_TYPE_DEBIT,
            balance=Decimal('101.00'),
        )
        AccountFactory(
            user=self.user,
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('202.00'),
        )
        Account.objects.create_deposit(
            user=self.user,
            name_account='Test deposit',
            bank=Bank.objects.get(pk=1),
            balance=Decimal('303.00'),
            currency='RUB',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('finance_account:list'))

        account_service = response.wsgi_request.container.core.account_service()
        accounts = Account.objects.by_user(self.user)
        self.assertEqual(
            response.context['sum_all_accounts_in_group'],
            account_service.get_balances_by_currency(accounts.debit()),
        )
        self.assertEqual(
            response.context['credit_balances_in_group'],
            account_service.get_balances_by_currency(accounts.credit()),
        )
        self.assertEqual(
            response.context['deposit_balances_in_group'],
            account_service.get_balances_by_currency(
                accounts.filter(type_account=ACCOUNT_TYPE_DEPOSIT),
            ),
        )

    def test_account_view_unauthenticated(self) -> None:
        """Test AccountView for unauthenticated user."""
        url = reverse('finance_account:list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_account_view_with_groups(self) -> None:
        """Test AccountView with user groups."""
        group = Group.objects.create(name='Test Group')
        self.user.groups.add(group)

        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('user_groups', response.context)

    def test_account_view_context_methods(self) -> None:
        """Test context data structure of AccountView."""
        view = AccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        setup_container_for_request(view.request)

        view.object_list = view.get_queryset()
        context = view.get_context_data()

        self.assertIn('accounts', context)
        self.assertIn('user_groups', context)
        self.assertIn('add_account_form', context)
        self.assertIn('transfer_money_form', context)
        self.assertIn('transfer_money_log', context)
        self.assertIn('sum_all_accounts', context)
        self.assertIn('sum_all_accounts_in_group', context)
        self.assertIn('credit_balances_in_group', context)
        self.assertIn('deposit_balances_in_group', context)

    def test_last_operations_include_transfers(self) -> None:
        from_account = Account.objects.get(pk=1)
        to_account = Account.objects.get(pk=2)
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=from_account,
            to_account=to_account,
            amount=Decimal('125.00'),
            exchange_date=timezone.now(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('finance_account:list'))

        operations = [
            item
            for day in response.context['last_operations']
            for item in day.items
        ]
        transfer_operation = next(
            item for item in operations if item.key == f'transfer-{transfer.pk}'
        )
        self.assertEqual(transfer_operation.source, 'transfer')
        self.assertEqual(transfer_operation.amount, Decimal())
        self.assertEqual(transfer_operation.transfer_amount, transfer.amount)
        self.assertEqual(
            transfer_operation.transfer_from_account_name,
            from_account.name_account,
        )
        self.assertEqual(
            transfer_operation.transfer_to_account_name,
            to_account.name_account,
        )


class TestFinancesView(TestCase):
    """Test cases for the combined finances view."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='finances-user',
            password='testpass123',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Card',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.other_account = Account.objects.create(
            user=self.user,
            name_account='Cash',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.other_account,
            category=self.expense_category,
            amount=Decimal('50.00'),
            date=timezone.now(),
        )
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        self.receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now(),
            operation_type=1,
            total_sum=Decimal('120.00'),
        )
        product = Product.objects.create(
            user=self.user,
            product_name='Milk',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Groceries',
            ),
            price=Decimal('120.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('120.00'),
        )
        self.receipt.product.add(product)

    def test_finances_include_receipt_as_single_expense(self) -> None:
        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(),
        )
        receipt_transactions = [tx for tx in transactions if tx.is_receipt]

        self.assertEqual(len(receipt_transactions), 1)
        self.assertEqual(receipt_transactions[0].amount, Decimal('-120.00'))
        self.assertEqual(
            receipt_transactions[0].category_name,
            'Покупки по чекам',
        )
        self.assertEqual(
            receipt_transactions[0].category_key,
            'receipt',
        )

    def test_finances_categories_include_receipt_category(self) -> None:
        categories = _finances_categories([self.user])

        self.assertIn(
            'receipt',
            {category.key for category in categories},
        )

    def test_finances_filter_receipts_by_account_and_category(self) -> None:
        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)
        finances_filter = FinancesFilter(
            account_ids=[self.account.pk],
            category_keys=['receipt'],
        )

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=finances_filter,
        )

        self.assertEqual(len(transactions), 1)
        self.assertTrue(transactions[0].is_receipt)
        self.assertEqual(
            transactions[0].account_name,
            self.account.name_account,
        )

    def test_finances_include_transfers_as_neutral_operations(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('75.00'),
            exchange_date=timezone.now(),
            notes='Card to cash',
        )
        request = self.factory.get('/finance/?type=transfer')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(type='transfer'),
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].key, f'transfer-{transfer.pk}')
        self.assertEqual(transactions[0].amount, Decimal())
        self.assertEqual(transactions[0].abs_amount, Decimal('75.00'))
        self.assertTrue(transactions[0].is_transfer)
        self.assertEqual(
            transactions[0].transfer_from_account_name,
            self.account.name_account,
        )
        self.assertEqual(
            transactions[0].transfer_to_account_name,
            self.other_account.name_account,
        )

    def test_finances_filter_transfers_by_account(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('80.00'),
            exchange_date=timezone.now(),
        )
        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(
                type='transfer',
                account_ids=[self.other_account.pk],
            ),
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].key, f'transfer-{transfer.pk}')

    def test_finances_searches_transaction_by_spaced_amount(self) -> None:
        transaction = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('116000.00'),
            date=timezone.now(),
        )
        request = self.factory.get('/finance/?q=116%20000')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(q='116 000'),
        )

        self.assertEqual(
            [item.source_id for item in transactions],
            [transaction.pk],
        )

    def test_finances_searches_transfer_by_amount(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('116000.00'),
            exchange_date=timezone.now(),
        )
        request = self.factory.get('/finance/?q=116000')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(q='116000'),
        )

        self.assertEqual(
            [item.source_id for item in transactions],
            [transfer.pk],
        )

    def test_finances_searches_receipt_by_decimal_amount(self) -> None:
        self.receipt.total_sum = Decimal('116000.50')
        self.receipt.save(update_fields=['total_sum'])
        request = self.factory.get('/finance/?q=116%20000%2C50')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(q='116 000,50'),
        )

        self.assertEqual(len(transactions), 1)
        self.assertTrue(transactions[0].is_receipt)

    def test_finances_search_field_has_stable_id_for_htmx_focus(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('finances'),
            HTTP_HX_REQUEST='true',
        )

        self.assertContains(response, 'id="finances-search"')

    def test_transfer_delete_view_reverses_balances(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('90.00'),
            exchange_date=timezone.now(),
        )
        self.account.balance = Decimal('910.00')
        self.account.save(update_fields=['balance'])
        self.other_account.balance = Decimal('1090.00')
        self.other_account.save(update_fields=['balance'])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('finance_account:transfer_delete', args=[transfer.pk]),
        )

        self.assertRedirects(response, reverse('finances'))
        self.account.refresh_from_db()
        self.other_account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(self.other_account.balance, Decimal('1000.00'))
        self.assertFalse(
            TransferMoneyLog.objects.filter(pk=transfer.pk).exists(),
        )

    def test_finances_filter_accepts_explicit_date_range(self) -> None:
        request = self.factory.get(
            '/finance/?date_from=2026-01-01&date_to=2026-01-31',
        )

        finances_filter = FinancesFilter.from_request(request)

        self.assertEqual(
            finances_filter.date_range(),
            (date(2026, 1, 1), date(2026, 1, 31)),
        )
        self.assertIn('date_from=01%2F01%2F2026', finances_filter.query_string)
        self.assertIn('date_to=31%2F01%2F2026', finances_filter.query_string)

    def test_finances_filter_accepts_legacy_date_aliases(self) -> None:
        request = self.factory.get(
            '/finance/?date_after=2026-02-01&date_before=2026-02-28',
        )

        finances_filter = FinancesFilter.from_request(request)

        self.assertEqual(
            finances_filter.date_range(),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )
        self.assertIn('date_from=01%2F02%2F2026', finances_filter.query_string)
        self.assertIn('date_to=28%2F02%2F2026', finances_filter.query_string)

    def test_finances_toolbar_renders_date_chip_with_date_only_flatpickr(
        self,
    ) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('finances'),
            HTTP_HX_REQUEST='true',
        )

        self.assertContains(response, 'data-finances-date-button')
        self.assertContains(response, 'data-flatpickr-mode="day-filter"')
        self.assertContains(response, 'Конкретная дата')

    def test_selecting_day_shows_formatted_date_on_active_chip(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('finances'),
            {'date_from': '2026-03-15', 'date_to': '2026-03-15'},
            HTTP_HX_REQUEST='true',
        )

        self.assertContains(response, '15.03.2026')

    def test_selecting_day_does_not_mark_month_preset_active(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('finances'),
            {'date_from': '2026-03-15', 'date_to': '2026-03-15'},
            HTTP_HX_REQUEST='true',
        )

        self.assertNotContains(
            response,
            'finances-pop-option is-active" data-finances-set='
            '"finances-period" data-finances-value="m"',
        )

    def test_general_reset_returns_to_current_month_label(self) -> None:
        self.assertEqual(FinancesFilter().period_label, 'Текущий месяц')

    def test_invalid_date_url_falls_back_to_default_period(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('finances'),
            {'date_from': 'not-a-date', 'date_to': 'also-bad'},
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, 'Текущий месяц')

    def test_selecting_day_disables_period_and_keeps_facets(self) -> None:
        request = self.factory.get(
            '/finance/?date_from=2026-03-15&date_to=2026-03-15'
            f'&period=m&type=expense&account={self.account.pk}',
        )

        finances_filter = FinancesFilter.from_request(request)

        self.assertEqual(
            finances_filter.selected_date,
            date(2026, 3, 15),
        )
        self.assertNotIn('period=', finances_filter.query_string)
        self.assertIn('type=expense', finances_filter.query_string)
        self.assertIn(
            f'account={self.account.pk}',
            finances_filter.query_string,
        )

    def test_selecting_period_disables_day(self) -> None:
        request = self.factory.get('/finance/?period=w')

        finances_filter = FinancesFilter.from_request(request)

        self.assertIsNone(finances_filter.selected_date)
        self.assertIn('period=w', finances_filter.query_string)
        self.assertNotIn('date_from', finances_filter.query_string)

    def test_day_filter_includes_all_sources_and_excludes_neighboring_days(
        self,
    ) -> None:
        target_day = date(2026, 3, 15)
        target_moment = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        neighbor_moment = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)

        target_tx = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('10.00'),
            date=target_moment,
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('20.00'),
            date=neighbor_moment,
        )
        self.receipt.receipt_date = target_moment
        self.receipt.save(update_fields=['receipt_date'])
        target_transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('30.00'),
            exchange_date=target_moment,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('40.00'),
            exchange_date=neighbor_moment,
        )

        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(
                date_from=target_day,
                date_to=target_day,
            ),
        )

        keys = {tx.key for tx in transactions}
        self.assertEqual(
            keys,
            {
                f'expense-{target_tx.pk}',
                f'transfer-{target_transfer.pk}',
                f'receipt-{self.receipt.pk}',
            },
        )

    def test_day_filter_combines_with_facets_via_and(self) -> None:
        target_day = date(2026, 3, 15)
        target_moment = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        matching = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('500.00'),
            date=target_moment,
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.other_account,
            category=self.expense_category,
            amount=Decimal('500.00'),
            date=target_moment,
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('10.00'),
            date=target_moment,
        )

        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(
                date_from=target_day,
                date_to=target_day,
                type='expense',
                account_ids=[self.account.pk],
                min_amount=Decimal('100.00'),
            ),
        )

        self.assertEqual(
            [tx.key for tx in transactions],
            [f'expense-{matching.pk}'],
        )

    def test_day_filter_or_within_accounts_and_categories(self) -> None:
        target_day = date(2026, 3, 15)
        target_moment = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        other_category = Category.objects.create(
            user=self.user,
            name='Transport',
            type=TransactionType.EXPENSE,
        )
        first_tx = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('10.00'),
            date=target_moment,
        )
        second_tx = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.other_account,
            category=other_category,
            amount=Decimal('10.00'),
            date=target_moment,
        )
        self.receipt.receipt_date = target_moment
        self.receipt.save(update_fields=['receipt_date'])

        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)

        transactions = _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(
                date_from=target_day,
                date_to=target_day,
                account_ids=[self.account.pk, self.other_account.pk],
                category_keys=[
                    f'expense-{self.expense_category.pk}',
                    f'expense-{other_category.pk}',
                    'receipt',
                ],
            ),
        )

        keys = {tx.key for tx in transactions}
        self.assertEqual(
            keys,
            {
                f'expense-{first_tx.pk}',
                f'expense-{second_tx.pk}',
                f'receipt-{self.receipt.pk}',
            },
        )

    def test_day_label_uses_active_timezone(self) -> None:
        with timezone.override(ZoneInfo('Pacific/Kiritimati')):
            today = timezone.localdate()
            self.assertEqual(_day_label(today), 'Сегодня')
            self.assertEqual(
                _day_label(today - timedelta(days=1)),
                'Вчера',
            )

    def test_transaction_near_utc_midnight_grouped_by_local_day(
        self,
    ) -> None:
        moment = datetime(2026, 3, 10, 23, 0, tzinfo=UTC)
        local_day = moment.astimezone(ZoneInfo('Pacific/Kiritimati')).date()
        self.assertNotEqual(local_day, moment.date())

        tx = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('15.00'),
            date=moment,
        )

        with timezone.override(ZoneInfo('Pacific/Kiritimati')):
            groups = _group_finances_by_day(
                [
                    tx_row
                    for tx_row in _finances_transactions(
                        request=self._authed_request(),
                        users=[self.user],
                        finances_filter=FinancesFilter(period='all'),
                    )
                    if tx_row.source_id == tx.pk
                ],
            )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].date, local_day)

    def test_dst_zone_sets_correct_local_day_boundary(self) -> None:
        berlin = ZoneInfo('Europe/Berlin')
        moment = datetime(2026, 3, 28, 23, 30, tzinfo=UTC)
        local_day = moment.astimezone(berlin).date()
        self.assertNotEqual(local_day, moment.date())

        tx = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('15.00'),
            date=moment,
        )

        with timezone.override(berlin):
            request = self._authed_request()
            same_day = _finances_transactions(
                request=request,
                users=[self.user],
                finances_filter=FinancesFilter(
                    date_from=local_day,
                    date_to=local_day,
                ),
            )
            previous_day = _finances_transactions(
                request=request,
                users=[self.user],
                finances_filter=FinancesFilter(
                    date_from=moment.date(),
                    date_to=moment.date(),
                ),
            )

        self.assertIn(f'expense-{tx.pk}', {t.key for t in same_day})
        self.assertNotIn(f'expense-{tx.pk}', {t.key for t in previous_day})

    def _authed_request(self) -> WSGIRequest:
        request = self.factory.get('/finance/')
        request.user = self.user
        setup_container_for_request(request)
        return request


class TestAccountCreateView(TestCase):
    """Test cases for AccountCreateView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',  # nosec B106: test-only password
        )

    def test_account_create_view_get(self) -> None:
        """Test GET request to AccountCreateView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('add_account_form', response.context)

    def test_account_create_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')

        data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        account = Account.objects.filter(user=self.user).first()
        self.assertIsNotNone(account)
        if account is None:
            msg = 'account should not be None'
            raise ValueError(msg)
        self.assertEqual(account.name_account, 'Test Account')

    def test_account_create_view_post_invalid(self) -> None:
        """Test POST request with invalid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')

        data = {
            'name_account': '',  # Invalid empty name
            'balance': Decimal('1000.00'),
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_account_create_view_get_context_data(self) -> None:
        """Test get_context_data method."""
        view = AccountCreateView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        view.object = None
        setup_container_for_request(view.request)

        context = view.get_context_data()
        self.assertIn('add_account_form', context)

    def test_account_create_view_get_success_url(self) -> None:
        """Test get_success_url method."""
        view = AccountCreateView()
        url = view.get_success_url()
        self.assertEqual(url, reverse_lazy('finance_account:list'))


class TestChangeAccountView(TestCase):
    """Test cases for ChangeAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.account = cast('Account', AccountFactory(user=self.user))
        self.factory = RequestFactory()

    def test_change_account_view_get(self) -> None:
        """Test GET request to ChangeAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:change', args=[self.account.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('add_account_form', response.context)

    def test_change_account_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:change', args=[self.account.pk])

        data = {
            'name_account': 'Updated Account Name',
            'type_account': ACCOUNT_TYPE_CREDIT,
            'limit_credit': Decimal('1000.00'),
            'payment_due_date': timezone.now().date(),
            'grace_period_days': 30,
            'balance': Decimal('3000.00'),
            'currency': 'EUR',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_change_account_view_get_context_data(self) -> None:
        """Test get_context_data method."""
        view = ChangeAccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        view.kwargs = {'pk': self.account.pk}
        view.object = self.account

        context = view.get_context_data()
        self.assertIn('add_account_form', context)


class TestTransferMoneyAccountView(TestCase):
    """Test cases for TransferMoneyAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = cast('User', UserFactory())
        self.account1 = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('1000.00'),
            ),
        )
        self.account2 = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('500.00'),
            ),
        )

    def test_transfer_money_view_get(self) -> None:
        """Test GET request to TransferMoneyAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_transfer_money_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')

        initial_balance1 = self.account1.balance
        initial_balance2 = self.account2.balance
        amount = Decimal('100.00')

        data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': amount,
            'exchange_date': timezone.now().strftime(
                constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            ),
            'notes': 'Test transfer',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()

        self.assertEqual(self.account1.balance, initial_balance1 - amount)
        self.assertEqual(self.account2.balance, initial_balance2 + amount)

    def test_transfer_money_view_remembers_last_account_pair(self) -> None:
        """A subsequent transfer should preselect the last successful pair."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')
        data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime(
                constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            ),
            'notes': 'Remember this pair',
        }
        self.client.post(url, data)

        response = self.client.get(url)
        form = response.context['form']

        self.assertEqual(form.fields['from_account'].initial, self.account1)
        self.assertEqual(form.fields['to_account'].initial, self.account2)

    def test_transfer_query_source_overrides_remembered_pair(self) -> None:
        """An explicit source account should override remembered defaults."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('100.00'),
            exchange_date=timezone.now(),
        )

        response = self.client.get(
            url,
            {'from_account': self.account2.pk},
        )
        form = response.context['form']

        self.assertEqual(form.fields['from_account'].initial, self.account2)
        self.assertEqual(form.fields['to_account'].initial, self.account1)

    def test_transfer_money_view_post_insufficient_funds(self) -> None:
        """Test POST request with insufficient funds."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')

        amount = self.account1.balance + Decimal('1000.00')

        data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': amount,
            'exchange_date': timezone.now().strftime(
                constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
            ),
            'notes': 'Test transfer',
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_transfer_money_view_get_form_kwargs(self) -> None:
        """Test get_form_kwargs method."""
        view = TransferMoneyAccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        setup_container_for_request(view.request)

        kwargs = view.get_form_kwargs()
        self.assertIn('user', kwargs)
        self.assertEqual(kwargs['user'], self.user)


class TestDeleteAccountView(TestCase):
    """Test cases for DeleteAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.account = cast('Account', AccountFactory(user=self.user))

    def test_delete_account_view_post(self) -> None:
        """Test POST request to DeleteAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:delete_account', args=[self.account.pk])

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_delete_account_view_success_url(self) -> None:
        """Test success_url property."""
        view = DeleteAccountView()
        url = view.success_url
        self.assertEqual(url, reverse_lazy('finance_account:list'))


class TestAjaxAccountsByGroupView(TestCase):
    """Test cases for AjaxAccountsByGroupView.

    NOTE: AjaxAccountsByGroupView has been removed and replaced with
    AccountsByGroupAPIView. These tests should be updated to test the API view.
    """

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.factory = RequestFactory()

    async def test_ajax_accounts_by_group_get(self) -> None:
        """Test GET request to AjaxAccountsByGroupView.

        NOTE: View removed - test disabled.
        """

    async def test_ajax_accounts_by_group_get_with_group_id(self) -> None:
        """Test GET request with specific group_id.

        NOTE: View removed - test disabled.
        """

    async def test_ajax_accounts_by_group_get_exception(self) -> None:
        """Test GET request handling exceptions.

        NOTE: View removed - test disabled.
        """


class TestQuickBankCreateView(TestCase):
    """Integration tests for the inline personal-bank quick-add endpoint."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.other_user = cast('User', UserFactory())
        self.client.force_login(self.user)

    def test_creates_personal_bank_and_returns_it(self) -> None:
        response = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Мой карманный банк'},
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['name'], 'Мой карманный банк')

        bank = Bank.objects.get(pk=payload['id'])
        self.assertEqual(bank.user, self.user)
        self.assertFalse(bank.is_system)

    def test_reuses_existing_personal_bank_with_same_name(self) -> None:
        first = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Банк повторно'},
        ).json()
        second = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Банк повторно'},
        ).json()

        self.assertEqual(first['id'], second['id'])
        self.assertEqual(
            Bank.objects.filter(user=self.user, name='Банк повторно').count(),
            1,
        )

    def test_rejects_blank_name(self) -> None:
        response = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': '   '},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        self.client.logout()
        response = self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Чужой банк'},
        )
        self.assertNotEqual(response.status_code, constants.SUCCESS_CODE)

    def test_personal_bank_is_scoped_to_its_owner(self) -> None:
        self.client.post(
            reverse('finance_account:quick_bank'),
            {'name': 'Приватный банк'},
        )
        bank = Bank.objects.get(name='Приватный банк')

        self.assertFalse(
            Bank.objects.filter(pk=bank.pk, user=self.other_user).exists(),
        )
        self.assertTrue(
            Bank.objects.filter(pk=bank.pk, user=self.user).exists(),
        )
