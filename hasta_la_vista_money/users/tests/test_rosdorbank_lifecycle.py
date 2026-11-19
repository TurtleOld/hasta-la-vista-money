"""RosDorBank lifecycle: reruns, untrusted refs, own transfers, cancels."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.test import TestCase, override_settings

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'rosdorbank_statement.pdf'
PAGO_PAGO = 'Pacific/Pago_Pago'


@statement_identity_settings
class RosDorBankLifecycleTest(TestCase):
    """Every RosDor representation stays traceable and moves no money."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def _upload(self) -> BankStatementUpload:
        with FIXTURE.open('rb') as pdf:
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=File(pdf, name='rosdorbank.pdf'),
            )
        process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        return upload

    def test_rerun_of_the_same_upload_keeps_one_position_set(self) -> None:
        upload = self._upload()
        before = list(
            upload.statement_rows.order_by('source_row_position').values_list(
                'source_row_position',
                'decision',
                'amount',
                'kind',
            ),
        )

        process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        after = list(
            upload.statement_rows.order_by('source_row_position').values_list(
                'source_row_position',
                'decision',
                'amount',
                'kind',
            ),
        )

        self.assertEqual(after, before)
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertFalse(
            TransferMoneyLog.objects.filter(user=self.user).exists(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_overlapping_file_keeps_untrusted_refs_local(self) -> None:
        first = self._upload()
        second = self._upload()

        second_rows = BankStatementRow.objects.filter(upload=second)
        self.assertEqual(second_rows.count(), 10)
        self.assertFalse(
            second_rows.exclude(duplicate_of=None).exists(),
        )
        self.assertFalse(
            second_rows.exclude(
                decision__in=(
                    BankStatementRow.Decision.AWAITING_MARKUP,
                    BankStatementRow.Decision.MUTUAL_CANCEL,
                ),
            ).exists(),
        )
        self.assertEqual(
            set(second_rows.values_list('source_ref_hash', flat=True)),
            set(first.statement_rows.values_list('source_ref_hash', flat=True)),
        )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertFalse(
            TransferMoneyLog.objects.filter(user=self.user).exists(),
        )

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_own_transfer_and_cancel_stay_visible_without_money(self) -> None:
        upload = self._upload()

        own = upload.statement_rows.get(amount=Decimal('700.00'))
        self.assertEqual(own.kind, 'own_c2c')
        self.assertEqual(
            own.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(own.bank_calendar_date, date(2026, 3, 2))
        cancels = upload.statement_rows.filter(kind='cancel')
        self.assertEqual(cancels.count(), 1)
        self.assertEqual(
            cancels.get().decision,
            BankStatementRow.Decision.MUTUAL_CANCEL,
        )
        self.assertFalse(
            TransferMoneyLog.objects.filter(user=self.user).exists(),
        )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_unresolved_root_cannot_be_closed_by_its_representation(
        self,
    ) -> None:
        upload = self._upload()
        root = upload.statement_rows.get(amount=Decimal('350.00'))
        child = upload.statement_rows.exclude(pk=root.pk).first()
        if child is None:
            self.fail('fixture has no second row')
        BankStatementRow.objects.filter(pk=child.pk).update(
            duplicate_of_id=root.pk,
        )

        service = ApplicationContainer().users.statement_markup_service()
        with self.assertRaises(StatementMarkupConflictError):
            service.post(child.pk, self.user.pk, None)

        root.refresh_from_db()
        child.refresh_from_db()
        self.assertIsNone(root.transaction_id)
        self.assertIsNone(child.transaction_id)
        self.assertNotEqual(
            child.decision,
            BankStatementRow.Decision.LINKED,
        )
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
