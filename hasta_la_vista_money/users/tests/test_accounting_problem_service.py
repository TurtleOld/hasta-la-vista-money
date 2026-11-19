"""Unified accounting problems service: owner scope, kinds, counts, filters."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.accounting_types import (
    AccountingProblemFilter,
    ProblemKind,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    FamilyGroupMembership,
    User,
)


class AccountingProblemServiceFixture(TestCase):
    """Synthetic statements covering every problem kind."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.sberbank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        self.ozon, _ = Bank.objects.get_or_create(
            code='OZON',
            defaults={'name': 'Ozon', 'is_system': True},
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Сбер основной',
            bank=self.sberbank,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.usd_account = Account.objects.create(
            user=self.user,
            name_account='Ozon валютный',
            bank=self.ozon,
            balance=Decimal('100.00'),
            currency='USD',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='sber.pdf',
            file_hash='hash-sber',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.markup_row = self._row(
            self.upload,
            1,
            BankStatementRow.Decision.AWAITING_MARKUP,
            day=date(2026, 3, 1),
            amount=Decimal('100.00'),
            transaction_type='expense',
        )
        self.pending_row = self._row(
            self.upload,
            2,
            BankStatementRow.Decision.PENDING,
            day=date(2026, 3, 2),
            amount=Decimal('200.00'),
            transaction_type='income',
        )
        self.repayment_row = self._row(
            self.upload,
            3,
            BankStatementRow.Decision.NEEDS_TRANSFER,
            day=date(2026, 3, 3),
            amount=Decimal('300.00'),
            transaction_type='expense',
        )
        self.deferred_row = self._row(
            self.upload,
            4,
            BankStatementRow.Decision.DEFERRED,
            day=None,
            amount=None,
            transaction_type='expense',
        )
        self.parse_error_row = self._row(
            self.upload,
            5,
            BankStatementRow.Decision.PARSE_ERROR,
            day=None,
            amount=None,
            transaction_type=None,
            parse_error_code=BankStatementRow.ParseError.MISSING_AMOUNT,
        )
        self.cleaned_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.usd_account,
            pdf_file='ozon.pdf',
            file_hash='hash-ozon',
            status=BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.expired_row = self._row(
            self.cleaned_upload,
            1,
            BankStatementRow.Decision.EXPIRED,
            day=date(2026, 2, 1),
            amount=Decimal('50.00'),
            transaction_type='expense',
        )
        self.cleaned_row = self._row(
            self.cleaned_upload,
            2,
            BankStatementRow.Decision.PENDING,
            day=None,
            amount=None,
            transaction_type=None,
            cleaned=True,
        )
        self.excluded_row = self._row(
            self.cleaned_upload,
            3,
            BankStatementRow.Decision.EXCLUDED,
            day=date(2026, 2, 2),
            amount=Decimal('999.00'),
            transaction_type='expense',
            reason='Оплата наличными',
        )
        self.failed_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='failed.pdf',
            file_hash='hash-failed',
            status=BankStatementUpload.Status.FAILED,
            error_message='Не удалось разобрать файл',
        )
        self.balance_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='balance.pdf',
            file_hash='hash-balance',
            status=BankStatementUpload.Status.COMPLETED,
            statement_closing_balance=Decimal('1000.00'),
            account_balance_after=Decimal('900.00'),
            balance_discrepancy=Decimal('100.00'),
        )
        self.other_user = User.objects.create_user(username='family-viewer')
        self.group = Group.objects.create(name='Accounting family')
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.other_user,
            role=FamilyGroupMembership.Role.VIEWER,
        )
        self.other_account = Account.objects.create(
            user=self.other_user,
            name_account='Чужой счёт',
            balance=Decimal('10.00'),
            currency='RUB',
        )
        self.other_upload = BankStatementUpload.objects.create(
            user=self.other_user,
            account=self.other_account,
            pdf_file='other.pdf',
            file_hash='hash-other',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.other_row = self._row(
            self.other_upload,
            1,
            BankStatementRow.Decision.DEFERRED,
            day=date(2026, 3, 5),
            amount=Decimal('777.00'),
            transaction_type='expense',
        )
        self.service = ApplicationContainer().users.accounting_problem_service()

    def _row(
        self,
        upload: BankStatementUpload,
        position: int,
        decision: str,
        *,
        day: date | None,
        amount: Decimal | None,
        transaction_type: str | None,
        parse_error_code: str = '',
        reason: str = '',
        cleaned: bool = False,
    ) -> BankStatementRow:
        moment = (
            datetime(
                day.year,
                day.month,
                day.day,
                12,
                tzinfo=timezone.get_current_timezone(),
            )
            if day is not None
            else None
        )
        return BankStatementRow.objects.create(
            upload=upload,
            transaction_type=transaction_type,
            transaction_date=moment,
            bank_calendar_date=day,
            amount=amount,
            description='' if cleaned else 'ПЯТЁРОЧКА',
            source_row_position=position,
            parse_error_code=parse_error_code,
            decision=decision,
            decision_reason=reason,
            data_cleaned_at=timezone.now() if cleaned else None,
        )

    def _kind_counts(self, **kwargs: Any) -> dict[str, int]:
        return dict(self.service.problems(self.user, **kwargs).counts.by_kind)


class AccountingProblemServiceTest(AccountingProblemServiceFixture):
    def test_returns_every_problem_kind_without_faking_unknown_fields(
        self,
    ) -> None:
        result = self.service.problems(self.user)
        counts = self._kind_counts()

        self.assertEqual(counts[ProblemKind.INCOMPLETE_MARKUP], 1)
        self.assertEqual(counts[ProblemKind.PROBABLE_DUPLICATE], 1)
        self.assertEqual(counts[ProblemKind.REPAYMENT], 1)
        self.assertEqual(counts[ProblemKind.DEFERRED], 1)
        self.assertEqual(counts[ProblemKind.PARSE_ERROR], 1)
        self.assertEqual(counts[ProblemKind.RECOVERY], 1)
        self.assertEqual(counts[ProblemKind.UPLOAD_FAILED], 1)
        self.assertEqual(counts[ProblemKind.BALANCE_ATTENTION], 1)
        self.assertEqual(result.counts.total_items, 8)

        deferred = next(
            item for item in result.items if item.kind == ProblemKind.DEFERRED
        )
        self.assertIsNone(deferred.transaction_date)
        self.assertFalse(deferred.date_known)
        self.assertIsNone(deferred.amount)
        self.assertFalse(deferred.amount_known)

        parse_error = next(
            item
            for item in result.items
            if item.kind == ProblemKind.PARSE_ERROR
        )
        self.assertIsNone(parse_error.transaction_date)
        self.assertIsNone(parse_error.amount)

    def test_cleaned_and_expired_rows_aggregate_once_per_upload(self) -> None:
        result = self.service.problems(self.user)
        recovery = [
            item for item in result.items if item.kind == ProblemKind.RECOVERY
        ]

        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].upload_id, self.cleaned_upload.pk)
        self.assertEqual(recovery[0].row_count, 2)
        self.assertIsNone(recovery[0].row_id)
        self.assertFalse(recovery[0].data_available)
        self.assertEqual(result.counts.recovery_row_count, 2)
        self.assertEqual(result.counts.total_items, 8)

        self.cleaned_row.refresh_from_db()
        self.expired_row.refresh_from_db()
        self.assertEqual(
            self.cleaned_row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(
            self.expired_row.decision,
            BankStatementRow.Decision.EXPIRED,
        )

    def test_excluded_rows_are_a_caveat_not_a_problem_item(self) -> None:
        result = self.service.problems(self.user)

        self.assertEqual(result.counts.excluded_row_count, 1)
        self.assertEqual(
            dict(result.excluded_reasons),
            {'Оплата наличными': 1},
        )
        self.assertFalse(
            any(item.row_id == self.excluded_row.pk for item in result.items),
        )
        self.assertEqual(result.counts.total_items, 8)

    def test_known_totals_stay_split_by_currency_and_direction(self) -> None:
        result = self.service.problems(self.user)
        totals = {
            (entry.currency, entry.direction): entry.amount
            for entry in result.totals
        }

        self.assertEqual(
            totals[('RUB', 'expense')],
            Decimal('400.00'),
        )
        self.assertEqual(
            totals[('RUB', 'income')],
            Decimal('200.00'),
        )
        self.assertEqual(
            totals[('USD', 'expense')],
            Decimal('50.00'),
        )
        self.assertTrue(result.totals_incomplete)

    def test_owner_only_even_for_family_reader(self) -> None:
        self.service.problems(self.user)

        family_result = self.service.problems(self.other_user)

        self.assertEqual(family_result.counts.total_items, 1)
        self.assertEqual(
            {item.account_id for item in family_result.items},
            {self.other_account.pk},
        )
        self.assertFalse(
            any(
                item.account_id == self.account.pk
                for item in family_result.items
            ),
        )
        with self.assertRaises(ValidationError):
            self.service.problems(
                self.other_user,
                account_ids=[self.account.pk],
            )

    def test_filters_by_account_bank_currency_kind_and_state(self) -> None:
        self.assertEqual(
            self.service.problems(
                self.user,
                account_ids=[self.account.pk],
            ).counts.total_items,
            7,
        )
        self.assertEqual(
            self.service.problems(
                self.user,
                filters=AccountingProblemFilter(bank_code='OZON'),
            ).counts.total_items,
            1,
        )
        self.assertEqual(
            self.service.problems(
                self.user,
                filters=AccountingProblemFilter(currency='USD'),
            ).counts.total_items,
            1,
        )
        self.assertEqual(
            self.service.problems(
                self.user,
                filters=AccountingProblemFilter(kind=ProblemKind.DEFERRED),
            ).counts.total_items,
            1,
        )
        self.assertEqual(
            self.service.problems(
                self.user,
                filters=AccountingProblemFilter(state='recovery'),
            ).counts.total_items,
            1,
        )

    def test_date_filter_keeps_rows_with_unknown_bank_date(self) -> None:
        result = self.service.problems(
            self.user,
            start=date(2026, 3, 2),
            end=date(2026, 3, 2),
        )
        kinds = [item.kind for item in result.items]

        self.assertIn(ProblemKind.PROBABLE_DUPLICATE, kinds)
        self.assertIn(ProblemKind.DEFERRED, kinds)
        self.assertIn(ProblemKind.PARSE_ERROR, kinds)
        self.assertNotIn(ProblemKind.INCOMPLETE_MARKUP, kinds)
        self.assertNotIn(ProblemKind.REPAYMENT, kinds)
        self.assertIn(ProblemKind.RECOVERY, kinds)
        self.assertEqual(result.counts.total_items, 6)

    def test_invalid_period_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.problems(
                self.user,
                start=date(2026, 3, 3),
                end=date(2026, 3, 1),
            )

    def test_no_object_is_duplicated_within_a_kind(self) -> None:
        result = self.service.problems(self.user)
        row_keys = [
            (item.kind, item.row_id)
            for item in result.items
            if item.row_id is not None
        ]
        upload_keys = [
            (item.kind, item.upload_id)
            for item in result.items
            if item.row_id is None
        ]

        self.assertEqual(len(row_keys), len(set(row_keys)))
        self.assertEqual(len(upload_keys), len(set(upload_keys)))

    def test_summary_matches_list_counters(self) -> None:
        list_result = self.service.problems(self.user)
        summary = self.service.summary(self.user)

        self.assertEqual(summary, list_result.counts)
        self.assertEqual(
            sum(summary.by_kind.values()),
            summary.total_items,
        )

    def test_result_is_immutable(self) -> None:
        result = self.service.problems(self.user)

        with self.assertRaises(FrozenInstanceError):
            result.counts.total_items = 0  # type: ignore[misc]
        with self.assertRaises(TypeError):
            result.counts.by_kind[ProblemKind.DEFERRED] = 2  # type: ignore[index]

    def test_query_count_does_not_grow_with_rows_or_uploads(self) -> None:
        with CaptureQueriesContext(connection) as base_queries:
            self.service.problems(self.user, account_ids=[self.account.pk])
        for index in range(4):
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=f'extra-{index}.pdf',
                file_hash=f'hash-extra-{index}',
                status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            )
            self._row(
                upload,
                1,
                BankStatementRow.Decision.DEFERRED,
                day=date(2026, 4, 1),
                amount=Decimal('10.00'),
                transaction_type='expense',
            )
        with CaptureQueriesContext(connection) as grown_queries:
            result = self.service.problems(
                self.user,
                account_ids=[self.account.pk],
            )

        self.assertEqual(len(base_queries), len(grown_queries))
        self.assertLessEqual(len(base_queries), 5)
        self.assertEqual(result.counts.total_items, 11)

    def test_service_never_moves_money(self) -> None:
        before = Transaction.objects.count()
        balances = list(
            Account.objects.filter(user=self.user)
            .order_by('pk')
            .values_list('balance', flat=True),
        )

        self.service.problems(self.user)

        self.assertEqual(Transaction.objects.count(), before)
        self.assertEqual(
            list(
                Account.objects.filter(user=self.user)
                .order_by('pk')
                .values_list('balance', flat=True),
            ),
            balances,
        )
