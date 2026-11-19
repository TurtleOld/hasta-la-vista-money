"""Unified accounting control page and its counters."""

from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


class AccountingControlViewFixture(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.bank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Сбер основной',
            bank=self.bank,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='sber.pdf',
            file_hash='hash-view-sber',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.deferred_row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type='expense',
            transaction_date=datetime(
                2026,
                3,
                1,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
            bank_calendar_date=date(2026, 3, 1),
            amount=Decimal('100.00'),
            description='ПЯТЁРОЧКА',
            source_row_position=1,
            decision=BankStatementRow.Decision.DEFERRED,
        )
        self.markup_row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type='expense',
            transaction_date=datetime(
                2026,
                3,
                2,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
            bank_calendar_date=date(2026, 3, 2),
            amount=Decimal('200.00'),
            description='МАГНИТ',
            source_row_position=2,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.failed_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='failed.pdf',
            file_hash='hash-view-failed',
            status=BankStatementUpload.Status.FAILED,
            error_message='Не удалось разобрать файл',
        )
        self.other_user = User.objects.create_user(username='outsider')
        self.other_account = Account.objects.create(
            user=self.other_user,
            name_account='Чужой счёт',
            balance=Decimal('5.00'),
            currency='RUB',
        )
        self.other_upload = BankStatementUpload.objects.create(
            user=self.other_user,
            account=self.other_account,
            pdf_file='other.pdf',
            file_hash='hash-view-other',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        BankStatementRow.objects.create(
            upload=self.other_upload,
            transaction_type='expense',
            amount=Decimal('777.00'),
            source_row_position=1,
            decision=BankStatementRow.Decision.DEFERRED,
        )
        self.service = ApplicationContainer().users.accounting_problem_service()

    def _url(self) -> str:
        return reverse('finance_account:accounting_control')


class AccountingControlViewTest(AccountingControlViewFixture):
    def test_requires_login(self) -> None:
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_owner_sees_unified_problems_and_existing_actions(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'finance_account/accounting_control.html',
        )
        problem_list = response.context['problem_list']
        self.assertEqual(problem_list.counts.total_items, 3)
        content = response.content.decode()
        self.assertIn('Сбер основной', content)
        self.assertIn('Отложена', content)
        self.assertIn('Ждёт разметки', content)
        self.assertIn(
            reverse(
                'finance_account:bank_statement_markup',
                args=[self.upload.pk],
            ),
            content,
        )
        self.assertIn(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            content,
        )
        self.assertIn(
            reverse('finance_account:bank_statement_upload'),
            content,
        )

    def test_other_users_statements_are_not_visible(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(self._url())

        self.assertNotIn('Чужой счёт', response.content.decode())
        self.assertEqual(
            {
                item.account_id
                for item in response.context['problem_list'].items
            },
            {self.account.pk},
        )

    def test_filter_by_kind_uses_the_same_service(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(self._url(), {'kind': 'deferred'})

        problem_list = response.context['problem_list']
        self.assertEqual(problem_list.counts.total_items, 1)
        self.assertEqual(
            [item.kind for item in problem_list.items],
            ['deferred'],
        )
        self.assertEqual(response.context['selected']['kind'], 'deferred')

    def test_foreign_account_filter_is_ignored(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            self._url(),
            {'account': str(self.other_account.pk)},
        )

        problem_list = response.context['problem_list']
        self.assertEqual(problem_list.counts.total_items, 3)
        self.assertNotIn('Чужой счёт', response.content.decode())

    def test_dashboard_counter_matches_service(self) -> None:
        self.client.force_login(self.user)
        expected = self.service.summary(self.user)

        response = self.client.get(reverse('users:dashboard'))

        self.assertEqual(
            response.context['accounting_problem_count'],
            expected.total_items,
        )
        self.assertContains(response, 'accounting-control')
        marker = f'data-accounting-problem-count="{expected.total_items}"'
        self.assertContains(response, marker)

    def test_header_badge_matches_service_on_another_page(self) -> None:
        self.client.force_login(self.user)
        expected = self.service.summary(self.user)

        response = self.client.get(reverse('finance_account:list'))

        marker = f'data-accounting-problem-count="{expected.total_items}"'
        self.assertContains(response, marker)
        self.assertContains(response, 'Контроль учёта')
