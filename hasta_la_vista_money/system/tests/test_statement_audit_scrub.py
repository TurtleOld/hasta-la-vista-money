"""Targeted anonymisation of raw statement refs in financial audit."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.statement_audit_scrub import (
    STATEMENT_SCRUB_FACT_OBJECT,
    STATEMENT_SOURCE_REF_SCRUBBED_LABEL,
    scrub_transaction_source_ref_audit,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class StatementAuditScrubTest(TestCase):
    """Only raw source refs in the linked movements' audit are replaced."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        self.moment = timezone.now()
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=self.moment,
            description='Покупка',
            source_ref='raw-bank-id',
        )
        self.transaction.source_ref = 'raw-bank-id-2'
        self.transaction.save(update_fields=['source_ref'])
        self.other = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('50.00'),
            date=self.moment,
            source_ref='other-raw',
        )

    def _transaction_logs(self, transaction: Transaction) -> list[AuditLog]:
        return list(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(transaction.pk),
            ).order_by('created_at', 'pk'),
        )

    def test_scrubs_created_and_changed_source_ref_values(self) -> None:
        before = {
            log.pk: (log.user_id, log.created_at, log.kind, log.action)
            for log in self._transaction_logs(self.transaction)
        }

        changed = scrub_transaction_source_ref_audit([self.transaction.pk])

        self.assertEqual(changed, 2)
        logs = self._transaction_logs(self.transaction)
        self.assertEqual(len(logs), 2)
        created = logs[0].diff['created']
        self.assertEqual(
            created['source_ref'],
            STATEMENT_SOURCE_REF_SCRUBBED_LABEL,
        )
        self.assertEqual(created['amount'], '100.00')
        self.assertEqual(created['category_id'], self.category.pk)
        self.assertEqual(created['description'], 'Покупка')
        changed_ref = logs[1].diff['changed']['source_ref']
        self.assertEqual(
            changed_ref,
            {
                'old': STATEMENT_SOURCE_REF_SCRUBBED_LABEL,
                'new': STATEMENT_SOURCE_REF_SCRUBBED_LABEL,
            },
        )
        for log in logs:
            self.assertEqual(
                before[log.pk],
                (log.user_id, log.created_at, log.kind, log.action),
            )
            self.assertNotIn('raw-bank-id', str(log.diff))

    def test_keeps_unrelated_transaction_audit_untouched(self) -> None:
        other_logs = self._transaction_logs(self.other)
        other_diffs = [log.diff for log in other_logs]

        scrub_transaction_source_ref_audit([self.transaction.pk])

        for log, diff in zip(
            self._transaction_logs(self.other),
            other_diffs,
            strict=True,
        ):
            self.assertEqual(log.diff, diff)
        self.assertIn(
            'other-raw',
            str(self._transaction_logs(self.other)[0].diff),
        )

    def test_scrub_is_idempotent(self) -> None:
        self.assertEqual(
            scrub_transaction_source_ref_audit([self.transaction.pk]),
            2,
        )
        diffs = [log.diff for log in self._transaction_logs(self.transaction)]

        self.assertEqual(
            scrub_transaction_source_ref_audit([self.transaction.pk]),
            0,
        )
        self.assertEqual(
            [log.diff for log in self._transaction_logs(self.transaction)],
            diffs,
        )

    def test_scrubs_delete_snapshot_without_losing_event(self) -> None:
        transaction_id = self.transaction.pk
        self.transaction.delete()

        scrub_transaction_source_ref_audit([transaction_id])

        deletion = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction_id),
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(
            deletion.diff['deleted']['source_ref'],
            STATEMENT_SOURCE_REF_SCRUBBED_LABEL,
        )
        self.assertEqual(deletion.diff['deleted']['amount'], '100.00')
        self.assertNotIn('raw-bank-id', str(deletion.diff))

    def _facts(self) -> list[AuditLog]:
        return list(
            AuditLog.objects.filter(
                model_name='users.BankStatementUpload',
                object_pk=STATEMENT_SCRUB_FACT_OBJECT,
            ).order_by('pk'),
        )

    def test_records_one_fact_without_removed_ids(self) -> None:
        scrub_transaction_source_ref_audit([self.transaction.pk])

        facts = self._facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].user_id, self.user.pk)
        self.assertEqual(facts[0].action, AuditLog.Action.UPDATE)
        self.assertEqual(
            facts[0].kind,
            AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        )
        self.assertEqual(
            facts[0].diff,
            {
                'bank_identifiers_anonymized': {
                    'old': False,
                    'new': True,
                },
                'entries': {'old': None, 'new': 2},
            },
        )
        rendered = str(facts[0].diff)
        self.assertNotIn('raw-bank-id', rendered)
        self.assertNotIn(str(self.transaction.pk), rendered)

    def test_repeat_does_not_record_another_fact(self) -> None:
        self.assertEqual(
            scrub_transaction_source_ref_audit([self.transaction.pk]),
            2,
        )
        self.assertEqual(len(self._facts()), 1)

        self.assertEqual(
            scrub_transaction_source_ref_audit([self.transaction.pk]),
            0,
        )
        self.assertEqual(len(self._facts()), 1)
