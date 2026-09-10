from decimal import Decimal

import structlog
from django.db import transaction
from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import (
    audit_operation,
    current_operation_id,
    current_operation_kind,
)
from hasta_la_vista_money.users.models import User

ACCOUNT_LABEL = 'finance_account.Account'


class AuditOperationContextTests(TestCase):
    """Entries written within one context share one operation."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='operation-user')

    def test_entries_created_inside_one_context_share_id_and_kind(
        self,
    ) -> None:
        with audit_operation(kind=AuditOperationKind.TRANSFER) as operation_id:
            first = Account.objects.create(user=self.user)
            second = Account.objects.create(user=self.user)

        logs = AuditLog.objects.filter(
            model_name=ACCOUNT_LABEL,
            object_pk__in=[str(first.pk), str(second.pk)],
        )
        self.assertEqual(logs.count(), 2)
        for log in logs:
            self.assertEqual(log.operation_id, operation_id)
            self.assertEqual(log.kind, AuditOperationKind.TRANSFER)

    def test_nested_context_overrides_outer_for_its_duration(self) -> None:
        with audit_operation(kind=AuditOperationKind.EXPENSE) as outer_id:
            outer_account = Account.objects.create(user=self.user)

            with audit_operation(kind=AuditOperationKind.INCOME) as inner_id:
                inner_account = Account.objects.create(user=self.user)

            after_account = Account.objects.create(user=self.user)

        self.assertNotEqual(outer_id, inner_id)

        outer_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(outer_account.pk),
        )
        inner_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(inner_account.pk),
        )
        after_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(after_account.pk),
        )
        self.assertEqual(outer_log.operation_id, outer_id)
        self.assertEqual(outer_log.kind, AuditOperationKind.EXPENSE)
        self.assertEqual(inner_log.operation_id, inner_id)
        self.assertEqual(inner_log.kind, AuditOperationKind.INCOME)
        self.assertEqual(after_log.operation_id, outer_id)
        self.assertEqual(after_log.kind, AuditOperationKind.EXPENSE)

    def test_each_context_entry_mints_a_fresh_operation_id(self) -> None:
        with audit_operation(kind=AuditOperationKind.EXPENSE) as first_id:
            pass
        with audit_operation(kind=AuditOperationKind.EXPENSE) as second_id:
            pass
        self.assertNotEqual(first_id, second_id)

    def test_context_is_cleared_after_exit(self) -> None:
        with audit_operation(kind=AuditOperationKind.EXPENSE):
            pass
        self.assertIsNone(current_operation_id())
        self.assertIsNone(current_operation_kind())

    def test_context_survives_nesting_inside_shared_atomic_block(
        self,
    ) -> None:
        """The ContextVar is not tied to the DB transaction.

        A context opened for one row inside an ``atomic`` block that spans
        the whole file must still group only that row's entries, and must
        not leak into the next row once its own context exits.
        """
        with transaction.atomic():
            with audit_operation(kind=AuditOperationKind.EXPENSE) as row_one_id:
                account_one = Account.objects.create(user=self.user)

            with audit_operation(kind=AuditOperationKind.INCOME) as row_two_id:
                account_two = Account.objects.create(user=self.user)

        log_one = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account_one.pk),
        )
        log_two = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account_two.pk),
        )
        self.assertEqual(log_one.operation_id, row_one_id)
        self.assertEqual(log_one.kind, AuditOperationKind.EXPENSE)
        self.assertEqual(log_two.operation_id, row_two_id)
        self.assertEqual(log_two.kind, AuditOperationKind.INCOME)


class AuditOperationKindTests(TestCase):
    """The kind vocabulary is declared closed and in full, per the ADR."""

    def test_kind_vocabulary_is_declared_in_full(self) -> None:
        expected = {
            'transfer',
            'receipt_purchase',
            'income',
            'expense',
            'transaction_edit',
            'transaction_delete',
            'receipt_edit',
            'receipt_delete',
            'account_edit',
            'account_delete',
            'statement_import',
            'statement_import_resolution',
        }
        self.assertEqual(
            {value for value, _ in AuditOperationKind.choices},
            expected,
        )


class AuditLogMissingOperationIdTests(TestCase):
    """A record without a context still writes, but warns."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='no-context-user')

    def test_entry_outside_any_context_has_no_operation_id(self) -> None:
        account = Account.objects.create(user=self.user)

        log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account.pk),
        )
        self.assertIsNone(log.operation_id)
        self.assertIsNone(log.kind)

    def test_missing_operation_id_logs_a_warning(self) -> None:
        with structlog.testing.capture_logs() as captured:
            Account.objects.create(user=self.user)

        warnings = [
            entry
            for entry in captured
            if entry['event'] == 'audit_log_missing_operation_id'
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['log_level'], 'warning')

    def test_context_suppresses_the_warning(self) -> None:
        with (
            structlog.testing.capture_logs() as captured,
            audit_operation(kind=AuditOperationKind.EXPENSE),
        ):
            Account.objects.create(user=self.user)

        warnings = [
            entry
            for entry in captured
            if entry['event'] == 'audit_log_missing_operation_id'
        ]
        self.assertEqual(warnings, [])

    def test_history_reads_without_error_for_entries_missing_operation_id(
        self,
    ) -> None:
        Account.objects.create(user=self.user)
        Account.objects.create(user=self.user)

        entries = list(
            AuditLog.objects.filter(user=self.user).order_by(
                '-created_at',
                '-id',
            ),
        )
        self.assertGreaterEqual(len(entries), 2)


class AuditLogOrderingTieBreakTests(TestCase):
    """Entries within the same second sort deterministically."""

    def test_ordering_tie_breaks_by_id_descending(self) -> None:
        user = User.objects.create_user(username='ordering-user')
        first = AuditLog.objects.create(
            user=user,
            model_name=ACCOUNT_LABEL,
            object_pk='1',
            action=AuditLog.Action.CREATE,
            diff={'v': 2, 'created': {'balance': str(Decimal('1.00'))}},
        )
        second = AuditLog.objects.create(
            user=user,
            model_name=ACCOUNT_LABEL,
            object_pk='2',
            action=AuditLog.Action.CREATE,
            diff={'v': 2, 'created': {'balance': str(Decimal('2.00'))}},
        )
        AuditLog.objects.filter(pk__in=[first.pk, second.pk]).update(
            created_at=first.created_at,
        )

        ordered = list(
            AuditLog.objects.filter(pk__in=[first.pk, second.pk]),
        )
        self.assertEqual(ordered, [second, first])
