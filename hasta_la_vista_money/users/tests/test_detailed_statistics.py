from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.constants import RECEIPT_OPERATION_PURCHASE
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.repositories import ProductCategoryRepository
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.cache import (
    get_user_detailed_statistics_cache_key,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    CardMonthDict,
    PaymentItemDict,
    PlanFactEngagementDict,
    StatisticsFilters,
    UserDetailedStatisticsDict,
    _apply_payments_to_months,
    get_user_detailed_statistics,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class GetUserDetailedStatisticsServiceTest(TestCase):
    """Tests for get_user_detailed_statistics service function."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_product.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
        'categories.yaml',
        'transactions.yaml',
    ]

    def setUp(self) -> None:
        cache.clear()
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def test_get_user_detailed_statistics(self) -> None:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        stats: UserDetailedStatisticsDict = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )
        self.assertIn('months_data', stats)
        self.assertIn('top_expense_categories', stats)
        self.assertIn('top_income_categories', stats)
        self.assertIn('receipt_info_by_month', stats)
        self.assertIn('income_expense', stats)
        self.assertIn('transfer_money_log', stats)
        self.assertIn('accounts', stats)
        self.assertIn('balances_by_currency', stats)
        self.assertIn('delta_by_currency', stats)
        self.assertIn('chart_combined', stats)
        self.assertIn('user', stats)
        self.assertIn('credit_cards_data', stats)
        self.assertIn('statistics_filter', stats)
        self.assertIn('statistics_members', stats)

    def test_chart_combined_keeps_shape_for_split_dynamics_charts(
        self,
    ) -> None:
        """chart_combined keeps its existing fields for the split charts.

        The dynamics tab renders a bar chart (income/expense) and a
        separate area chart (balance forecast band) from the same
        aggregate — this test pins the field shapes so the frontend
        split does not require any change to this service function.
        """
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        stats: UserDetailedStatisticsDict = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )
        chart_combined = stats['chart_combined']
        for key in (
            'labels',
            'income_data',
            'expense_data',
            'forecast_balance',
            'forecast_lower',
            'forecast_upper',
        ):
            if key not in chart_combined:
                self.fail(f'chart_combined is missing key {key!r}')
            self.assertIsInstance(chart_combined[key], list)

    def test_get_user_detailed_statistics_uses_cached_value(self) -> None:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        cache_key = get_user_detailed_statistics_cache_key(
            self.user.pk,
            stats_filter.cache_suffix,
        )
        cached_stats = cast(
            'UserDetailedStatisticsDict',
            {
                'months_data': [],
                'top_expense_categories': [],
                'top_income_categories': [],
                'receipt_info_by_month': [],
                'income_expense': [],
                'transfer_money_log': [],
                'accounts': [],
                'balances_by_currency': {},
                'delta_by_currency': {},
                'chart_combined': {},
                'user': self.user,
                'credit_cards_data': [],
                'statistics_filter': stats_filter,
                'statistics_period_choices': [],
                'statistics_account_choices': [],
                'statistics_currency_choices': [],
                'statistics_category_choices': [],
                'statistics_member_choices': [],
                'statistics_members': [self.user],
            },
        )
        cache.set(cache_key, cached_stats, 600)

        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

        self.assertEqual(stats, cached_stats)

    def test_statistics_filters_include_server_side_search_fields(self) -> None:
        query = QueryDict(
            'operations_search=salary&transfers_search=sber'
            '&receipts_search=pyaterochka',
        )
        stats_filter = StatisticsFilters.from_query(query)

        self.assertEqual(stats_filter.operations_search, 'salary')
        self.assertEqual(stats_filter.transfers_search, 'sber')
        self.assertEqual(stats_filter.receipts_search, 'pyaterochka')
        self.assertIn('operations_search=salary', stats_filter.query_string)
        self.assertIn('transfers_search=sber', stats_filter.query_string)
        self.assertIn('receipts_search=pyaterochka', stats_filter.query_string)

    def test_receipts_search_filters_receipt_page(self) -> None:
        container = ApplicationContainer()
        base_filter = StatisticsFilters(
            period='range',
            date_from=date(2000, 1, 1),
            date_to=timezone.localdate(),
        )
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=base_filter,
        )
        base_receipts = list(base_stats['receipt_page'].paginator.object_list)
        self.assertTrue(base_receipts)

        first_receipt = base_receipts[0]
        search_value = first_receipt.account.name_account
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(
                period='range',
                date_from=date(2000, 1, 1),
                date_to=timezone.localdate(),
                receipts_search=search_value,
            ),
        )

        filtered_receipts = list(
            filtered_stats['receipt_page'].paginator.object_list,
        )
        self.assertTrue(filtered_receipts)
        for receipt in filtered_receipts:
            self.assertIn(
                search_value.lower(),
                receipt.account.name_account.lower(),
            )

    def test_receipt_category_shares_known_categories_and_sums(self) -> None:
        """Category-share aggregation sums per `ProductCategory`."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        seller = Seller.objects.create(
            user=self.user,
            name_seller='Донат-тест магазин',
        )
        category_repo = ProductCategoryRepository()
        drinks = category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        dairy = category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты',
        )

        drink_a = Product.objects.create(
            user=self.user,
            product_name='Чай',
            category=drinks,
            price=Decimal('100.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('100.00'),
        )
        drink_b = Product.objects.create(
            user=self.user,
            product_name='Кофе',
            category=drinks,
            price=Decimal('50.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('50.00'),
        )
        milk = Product.objects.create(
            user=self.user,
            product_name='Молоко',
            category=dairy,
            price=Decimal('50.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('50.00'),
        )
        uncategorized = Product.objects.create(
            user=self.user,
            product_name='Разное',
            category=None,
            price=Decimal('25.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('25.00'),
        )

        receipt = Receipt.objects.create(
            user=self.user,
            seller=seller,
            account=account,
            receipt_date='2026-01-15 12:00:00',
            number_receipt=555001,
            operation_type=RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('225.00'),
        )
        receipt.product.add(drink_a, drink_b, milk, uncategorized)

        container = ApplicationContainer()
        stats_filter = StatisticsFilters(
            period='range',
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

        shares_by_category = {
            item['category_name']: item
            for item in stats['receipt_category_shares']
        }
        self.assertIn('Напитки', shares_by_category)
        self.assertIn('Молочные продукты', shares_by_category)
        self.assertIn('Без категории', shares_by_category)

        self.assertAlmostEqual(shares_by_category['Напитки']['total'], 150.0)
        self.assertAlmostEqual(
            shares_by_category['Молочные продукты']['total'],
            50.0,
        )
        self.assertAlmostEqual(
            shares_by_category['Без категории']['total'],
            25.0,
        )
        self.assertAlmostEqual(
            shares_by_category['Напитки']['percent'],
            150 / 225 * 100,
        )
        self.assertAlmostEqual(
            shares_by_category['Без категории']['percent'],
            25 / 225 * 100,
        )

        chart = stats['receipt_category_chart']
        self.assertEqual(
            set(chart['labels']),
            {'Напитки', 'Молочные продукты', 'Без категории'},
        )

    def test_receipt_category_products_view_returns_category_products(
        self,
    ) -> None:
        """Htmx drill-down lists only products in the requested category."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        seller = Seller.objects.create(
            user=self.user,
            name_seller='Дриллдаун магазин',
        )
        category = ProductCategoryRepository().get_or_create_category(
            user=self.user,
            name='Бытовая химия',
        )
        in_category = Product.objects.create(
            user=self.user,
            product_name='Стиральный порошок',
            category=category,
            price=Decimal('300.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('300.00'),
        )
        other_product = Product.objects.create(
            user=self.user,
            product_name='Хлеб',
            category=None,
            price=Decimal('60.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('60.00'),
        )
        receipt = Receipt.objects.create(
            user=self.user,
            seller=seller,
            account=account,
            receipt_date='2026-02-10 10:00:00',
            number_receipt=555002,
            operation_type=RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('360.00'),
        )
        receipt.product.add(in_category, other_product)

        self.client.force_login(self.user)
        url = reverse('users:statistics_receipts_category_products')
        response = self.client.get(
            url,
            {
                'category_id': str(category.pk),
                'period': 'range',
                'date_from': '2026-02-01',
                'date_to': '2026-02-28',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Стиральный порошок')
        self.assertNotContains(response, 'Хлеб')

    def test_operations_search_filters_income_expense(self) -> None:
        container = ApplicationContainer()
        base_filter = StatisticsFilters(
            period='range',
            date_from=date(2000, 1, 1),
            date_to=timezone.localdate(),
        )
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=base_filter,
        )
        base_operations = base_stats['income_expense']
        self.assertTrue(base_operations)

        first_operation = base_operations[0]
        search_value = str(first_operation['category__name'])
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(
                period='range',
                date_from=date(2000, 1, 1),
                date_to=timezone.localdate(),
                operations_search=search_value,
            ),
        )

        filtered_operations = filtered_stats['income_expense']
        self.assertTrue(filtered_operations)
        for operation in filtered_operations:
            self.assertIn(
                search_value.lower(),
                str(operation['category__name']).lower(),
            )

    def test_plan_fact_summary_and_top_deviations(self) -> None:
        """Plan/Fact summary totals and top-5 deviations match fixtures."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        expense_category = Category.objects.create(
            user=self.user,
            name='Plan/Fact expense category',
            type=TransactionType.EXPENSE,
        )
        income_category = Category.objects.create(
            user=self.user,
            name='Plan/Fact income category',
            type=TransactionType.INCOME,
        )

        Planning.objects.create(
            user=self.user,
            category=expense_category,
            date=date(2026, 1, 1),
            amount=Decimal('1000.00'),
            planning_type=TransactionType.EXPENSE,
        )
        Planning.objects.create(
            user=self.user,
            category=income_category,
            date=date(2026, 1, 1),
            amount=Decimal('500.00'),
            planning_type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=expense_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('700.00'),
            date=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=income_category,
            type=TransactionType.INCOME,
            amount=Decimal('800.00'),
            date=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
        )

        container = ApplicationContainer()
        stats_filter = StatisticsFilters(
            period='range',
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

        self.assertIn('plan_fact_summary', stats)
        self.assertIn('plan_fact_top_deviations', stats)

        summary = stats['plan_fact_summary']
        self.assertEqual(summary['expense']['fact'], 700.0)
        self.assertEqual(summary['expense']['plan'], 1000.0)
        self.assertEqual(summary['expense']['diff'], -300.0)
        self.assertEqual(summary['income']['fact'], 800.0)
        self.assertEqual(summary['income']['plan'], 500.0)
        self.assertEqual(summary['income']['diff'], 300.0)

        deviations = stats['plan_fact_top_deviations']
        self.assertEqual(len(deviations), 2)
        category_names = {item['category_name'] for item in deviations}
        self.assertEqual(
            category_names,
            {expense_category.name, income_category.name},
        )
        for item in deviations:
            if item['category_id'] == expense_category.pk:
                self.assertEqual(item['fact'], 700.0)
                self.assertEqual(item['plan'], 1000.0)
                self.assertEqual(item['diff'], -300.0)
                self.assertEqual(item['abs_diff'], 300.0)
            else:
                self.assertEqual(item['category_id'], income_category.pk)
                self.assertEqual(item['fact'], 800.0)
                self.assertEqual(item['plan'], 500.0)
                self.assertEqual(item['diff'], 300.0)
                self.assertEqual(item['abs_diff'], 300.0)

    def _plan_fact_engagement_for_period(
        self,
        account: Account,
        *,
        category_amounts: list[tuple[Decimal, Decimal]],
        period_start: date,
        period_end: date,
    ) -> PlanFactEngagementDict:
        """Create expense categories with the given (plan, fact) pairs."""
        for index, (plan_amount, fact_amount) in enumerate(category_amounts):
            category = Category.objects.create(
                user=self.user,
                name=f'Engagement category {index}',
                type=TransactionType.EXPENSE,
            )
            Planning.objects.create(
                user=self.user,
                category=category,
                date=period_start,
                amount=plan_amount,
                planning_type=TransactionType.EXPENSE,
            )
            if fact_amount:
                Transaction.objects.create(
                    user=self.user,
                    account=account,
                    category=category,
                    type=TransactionType.EXPENSE,
                    amount=fact_amount,
                    date=datetime.combine(
                        period_start,
                        time(12, 0),
                        tzinfo=UTC,
                    ),
                )

        container = ApplicationContainer()
        stats_filter = StatisticsFilters(
            period='range',
            date_from=period_start,
            date_to=period_end,
        )
        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )
        return stats['plan_fact_engagement']

    def test_plan_fact_engagement_savings(self) -> None:
        """Fact under plan in every category shows up as savings."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        engagement = self._plan_fact_engagement_for_period(
            account,
            category_amounts=[
                (Decimal('1000.00'), Decimal('500.00')),
                (Decimal('1000.00'), Decimal('800.00')),
            ],
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

        self.assertEqual(engagement['categories_with_plan'], 2)
        self.assertEqual(engagement['categories_within_plan'], 2)
        self.assertEqual(engagement['diff'], -700.0)
        self.assertEqual(engagement['abs_diff'], 700.0)

    def test_plan_fact_engagement_overspend(self) -> None:
        """Fact over plan in every category shows up as overspend."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        engagement = self._plan_fact_engagement_for_period(
            account,
            category_amounts=[
                (Decimal('500.00'), Decimal('800.00')),
                (Decimal('500.00'), Decimal('900.00')),
            ],
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        )

        self.assertEqual(engagement['categories_with_plan'], 2)
        self.assertEqual(engagement['categories_within_plan'], 0)
        self.assertEqual(engagement['diff'], 700.0)
        self.assertEqual(engagement['abs_diff'], 700.0)

    def test_plan_fact_engagement_exact_plan(self) -> None:
        """Fact exactly matching plan is reported as 'точно по плану'."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        engagement = self._plan_fact_engagement_for_period(
            account,
            category_amounts=[(Decimal('1000.00'), Decimal('1000.00'))],
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )

        self.assertEqual(engagement['categories_with_plan'], 1)
        self.assertEqual(engagement['categories_within_plan'], 1)
        self.assertEqual(engagement['diff'], 0.0)
        self.assertEqual(engagement['abs_diff'], 0.0)

    def test_suggested_plan_categories(self) -> None:
        """Suggested plan lists only unplanned categories spent in 3mo."""
        account = Account.objects.first()
        if account is None:
            msg = 'No account found in fixtures'
            raise ValueError(msg)

        today = timezone.now().date()
        recent_month = today.replace(day=1) - relativedelta(months=1)
        stale_month = today.replace(day=1) - relativedelta(months=4)

        unplanned_category = Category.objects.create(
            user=self.user,
            name='Unplanned recent spend',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=unplanned_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('900.00'),
            date=datetime.combine(recent_month, time(12, 0), tzinfo=UTC),
        )

        stale_category = Category.objects.create(
            user=self.user,
            name='Unplanned stale spend',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=stale_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('5000.00'),
            date=datetime.combine(stale_month, time(12, 0), tzinfo=UTC),
        )

        planned_category = Category.objects.create(
            user=self.user,
            name='Already planned spend',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=planned_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('700.00'),
            date=datetime.combine(recent_month, time(12, 0), tzinfo=UTC),
        )
        Planning.objects.create(
            user=self.user,
            category=planned_category,
            date=today,
            amount=Decimal('700.00'),
            planning_type=TransactionType.EXPENSE,
        )

        container = ApplicationContainer()
        stats_filter = StatisticsFilters(
            period='range',
            date_from=today.replace(day=1) - relativedelta(months=6),
            date_to=today,
        )
        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

        suggestions = stats['suggested_plan_categories']
        category_ids = {item['category_id'] for item in suggestions}

        self.assertIn(unplanned_category.pk, category_ids)
        self.assertNotIn(stale_category.pk, category_ids)
        self.assertNotIn(planned_category.pk, category_ids)
        self.assertLessEqual(len(suggestions), 5)

        for item in suggestions:
            if item['category_id'] == unplanned_category.pk:
                self.assertAlmostEqual(item['suggested_amount'], 300.0)

    def test_statistics_template_contains_htmx_server_side_controls(
        self,
    ) -> None:
        self.client.force_login(self.user)
        response = self.client.get('/users/statistics/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="statistics-content"')
        self.assertContains(response, 'id="statistics-results"')
        self.assertContains(
            response,
            'class="statistics-panel statistics-filter-form"',
        )
        self.assertContains(response, 'hx-target="#statistics-content"')
        self.assertContains(response, 'name="operations_search"')
        self.assertContains(response, 'name="transfers_search"')
        self.assertContains(response, 'name="receipts_search"')
        self.assertContains(response, 'hx-target="#statistics-results"')
        self.assertContains(response, 'id="incomeExpenseChart"')
        self.assertContains(response, 'id="balanceForecastChart"')

    def test_statistics_template_renders_plan_fact_tab(self) -> None:
        """The renamed Plan/Fact tab renders its sections and budget link."""
        self.client.force_login(self.user)
        response = self.client.get('/users/statistics/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'План/Факт')
        self.assertNotContains(response, '>Бюджеты<')
        self.assertContains(response, 'data-panel="budgets"')
        self.assertContains(response, 'Топ-5 отклонений факт/план')
        self.assertContains(response, 'Лимиты')
        self.assertContains(response, 'Открыть полную таблицу')
        self.assertContains(response, reverse('budget:list'))


class CreditCardPaymentScheduleTest(TestCase):
    """Tests for credit card payment distribution."""

    def test_payments_after_grace_end_do_not_close_month(self) -> None:
        grace_end = timezone.make_aware(
            datetime.combine(date(2026, 8, 28), time.max),
        )
        months: list[CardMonthDict] = [
            {
                'month': '05.2026',
                'purchase_start': timezone.now(),
                'purchase_end': timezone.now(),
                'grace_end': grace_end,
                'debt_for_month': 10000.0,
                'is_overdue': False,
                'days_until_due': 0,
                'payments_made': 0.0,
                'remaining_debt': 0.0,
                'is_paid': False,
            },
        ]
        payments: list[PaymentItemDict] = [
            {
                'amount': Decimal('10000.00'),
                'date': grace_end + timedelta(days=1),
            },
        ]

        _apply_payments_to_months(months, payments)

        self.assertEqual(months[0]['payments_made'], 0.0)
        self.assertEqual(months[0]['remaining_debt'], 10000.0)
        self.assertFalse(months[0]['is_paid'])


class SummaryCardsAndMovingAverageTest(TestCase):
    """Tests for summary-card deltas and the expense moving average.

    Builds four consecutive months of known expense/income totals (no
    shared fixtures) so the previous-month delta and the 3-month moving
    average can be checked against hand-computed values.
    """

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            username='dynamicsuser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Расходы',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Доходы',
            type=TransactionType.INCOME,
        )
        self.today = timezone.now().date()

        # Known monthly totals, oldest to newest: -3, -2, -1, 0 (current).
        self.monthly_expenses = [
            Decimal('1000.00'),
            Decimal('2000.00'),
            Decimal('3000.00'),
            Decimal('4000.00'),
        ]
        self.monthly_income = Decimal('3000.00')
        for months_ago, expense_amount in zip(
            (3, 2, 1, 0),
            self.monthly_expenses,
            strict=True,
        ):
            month_date = self._month_date(months_ago)
            Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=expense_amount,
                date=month_date,
                type=TransactionType.EXPENSE,
            )
            Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=self.monthly_income,
                date=month_date,
                type=TransactionType.INCOME,
            )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _month_date(self, months_ago: int, day: int = 1) -> datetime:
        base = self.today.replace(day=1) - relativedelta(months=months_ago)
        safe_day = min(day, monthrange(base.year, base.month)[1])
        return datetime(base.year, base.month, safe_day, 12, 0, tzinfo=UTC)

    def _get_stats(self) -> UserDetailedStatisticsDict:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters(period='4')
        return get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

    def test_summary_cards_delta_vs_previous_month(self) -> None:
        """Cards compare the last month in the period to the one before."""
        stats = self._get_stats()
        cards_by_key = {card['key']: card for card in stats['summary_cards']}

        expenses_card = cards_by_key['expenses']
        self.assertEqual(expenses_card['value'], 4000.0)
        self.assertEqual(expenses_card['delta'], 1000.0)
        if expenses_card['delta_percent'] is None:
            self.fail('expenses delta_percent should not be None')
        self.assertAlmostEqual(
            expenses_card['delta_percent'],
            1000.0 / 3000.0 * 100,
        )
        self.assertFalse(expenses_card['positive_is_good'])

        income_card = cards_by_key['income']
        self.assertEqual(income_card['value'], 3000.0)
        self.assertEqual(income_card['delta'], 0.0)
        self.assertTrue(income_card['positive_is_good'])

        savings_card = cards_by_key['savings']
        self.assertEqual(savings_card['value'], 3000.0 - 4000.0)
        self.assertEqual(savings_card['delta'], -1000.0)
        self.assertIsNone(savings_card['delta_percent'])
        self.assertTrue(savings_card['positive_is_good'])

    def test_expense_moving_average_over_three_months(self) -> None:
        """The moving average needs a full 3-month trailing window."""
        stats = self._get_stats()
        months_data = stats['months_data']
        self.assertEqual(len(months_data), 4)
        self.assertEqual(
            [month.get('expenses') for month in months_data],
            [float(amount) for amount in self.monthly_expenses],
        )

        chart_combined = stats['chart_combined']
        labels = chart_combined['labels']
        moving_average = chart_combined['expense_moving_average']
        by_date = dict(zip(labels, moving_average, strict=False))

        expected_by_months_ago = {
            3: None,
            2: None,
            1: (1000.0 + 2000.0 + 3000.0) / 3,
            0: (2000.0 + 3000.0 + 4000.0) / 3,
        }
        for months_ago, expected_value in expected_by_months_ago.items():
            transaction_date = self._month_date(months_ago).date().isoformat()
            self.assertIn(transaction_date, by_date)
            self.assertEqual(by_date[transaction_date], expected_value)
