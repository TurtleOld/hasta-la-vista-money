"""A repayment row closes only by a transfer made from that row."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services.transfer_service import (
        TransferService,
    )

WHEN = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)
AMOUNT = Decimal('199.00')


class RepaymentRowTransferBase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='repayer',
            password='testpass123',  # nosec B106: test-only password
        )
        self.card = self._account(self.user, ACCOUNT_TYPE_CREDIT_CARD)
        self.debit = self._account(self.user, ACCOUNT_TYPE_DEBIT_CARD)
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.card,
            pdf_file='bank_statements/card.pdf',
        )
        self.row = self._row(self.upload)
        self.transfer_service: TransferService = (
            ApplicationContainer().finance_account.transfer_service()
        )

    @staticmethod
    def _account(user: User, type_account: str) -> Account:
        return Account.objects.create(
            user=user,
            name_account=type_account,
            type_account=type_account,
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    @staticmethod
    def _row(
        upload: BankStatementUpload,
        decision: str = BankStatementRow.Decision.NEEDS_TRANSFER,
        position: int = 0,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=AMOUNT,
            description='Перевод на карту',
            decision=decision,
        )

    def _transfer(
        self,
        row_id: int | None,
        amount: Decimal = AMOUNT,
        to_account: Account | None = None,
    ) -> TransferMoneyLog:
        return self.transfer_service.transfer_money(
            from_account=self.debit,
            to_account=to_account or self.card,
            amount=amount,
            user=self.user,
            exchange_date=WHEN,
            statement_row_id=row_id,
        )

    def _assert_refused(
        self,
        row_id: int,
        amount: Decimal = AMOUNT,
        to_account: Account | None = None,
    ) -> None:
        with self.assertRaises(ValidationError):
            self._transfer(row_id, amount=amount, to_account=to_account)
        self.assertFalse(TransferMoneyLog.objects.exists())
        self.card.refresh_from_db()
        self.debit.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))
        self.assertEqual(self.debit.balance, Decimal('1000.00'))


class RepaymentRowTransferServiceTest(RepaymentRowTransferBase):
    def test_transfer_from_row_closes_that_row(self) -> None:
        other = self._row(self.upload, position=1)

        transfer = self._transfer(self.row.pk)

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(self.row.transfer, transfer)
        self.assertIsNotNone(self.row.decided_at)
        self.assertTrue(
            BankStatementDecisionAudit.objects.filter(
                row=self.row,
                actor=self.user,
                decision=BankStatementRow.Decision.TRANSFERRED,
            ).exists(),
        )
        other.refresh_from_db()
        self.assertEqual(
            other.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.needs_transfer_count, 1)

    def test_transfer_without_row_keeps_matching_row_open(self) -> None:
        self._transfer(None)

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertIsNone(self.row.transfer)

    def test_closed_row_refuses_transfer(self) -> None:
        for decision in (
            BankStatementRow.Decision.TRANSFERRED,
            BankStatementRow.Decision.NOT_A_PAYMENT,
        ):
            with self.subTest(decision=decision):
                self.row.decision = decision
                self.row.save(update_fields=['decision'])
                self._assert_refused(self.row.pk)

    def test_amount_mismatch_refuses_transfer(self) -> None:
        self._assert_refused(self.row.pk, amount=Decimal('200.00'))

    def test_row_of_other_account_refuses_transfer(self) -> None:
        other_card = self._account(self.user, ACCOUNT_TYPE_CREDIT_CARD)

        self._assert_refused(self.row.pk, to_account=other_card)

    def test_row_of_other_user_refuses_transfer(self) -> None:
        stranger = User.objects.create_user(username='stranger')
        foreign_card = self._account(stranger, ACCOUNT_TYPE_CREDIT_CARD)
        foreign_upload = BankStatementUpload.objects.create(
            user=stranger,
            account=foreign_card,
            pdf_file='bank_statements/foreign.pdf',
        )
        foreign_row = self._row(foreign_upload)

        self._assert_refused(foreign_row.pk)

    def test_delete_transfer_returns_repayment_row_to_needs_transfer(
        self,
    ) -> None:
        transfer = self._transfer(self.row.pk)

        self.transfer_service.delete_transfer(
            transfer_id=transfer.pk,
            user=self.user,
        )

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertIsNone(self.row.transfer)
        self.assertIsNone(self.row.decided_at)
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.needs_transfer_count, 1)


class RepaymentRowTransferViewTest(RepaymentRowTransferBase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)

    def _post(self, row_id: int | str) -> Any:
        return self.client.post(
            reverse('finance_account:transfer_money'),
            {
                'from_account': self.debit.pk,
                'to_account': self.card.pk,
                'amount': '199.00',
                'exchange_date': '2026-02-09T12:00',
                'notes': '',
                'statement_row': row_id,
            },
        )

    def test_account_list_get_does_not_close_rows(self) -> None:
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=AMOUNT,
            exchange_date=WHEN,
        )

        response = self.client.get(reverse('finance_account:list'))

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertContains(response, f'statement_row={self.row.pk}')

    def test_transfer_form_keeps_row_in_hidden_field(self) -> None:
        response = self.client.get(
            reverse('finance_account:transfer_money'),
            {'to_account': self.card.pk, 'statement_row': self.row.pk},
        )

        self.assertContains(
            response,
            f'type="hidden" name="statement_row" value="{self.row.pk}"',
        )

    def test_post_with_row_closes_it(self) -> None:
        response = self._post(self.row.pk)

        self.assertRedirects(
            response,
            reverse('finance_account:list'),
            fetch_redirect_response=False,
        )
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )

    def test_post_with_closed_row_shows_error(self) -> None:
        self.row.decision = BankStatementRow.Decision.NOT_A_PAYMENT
        self.row.save(update_fields=['decision'])

        response = self._post(self.row.pk)

        self.assertContains(response, 'Строка выписки уже закрыта')
        self.assertFalse(TransferMoneyLog.objects.exists())

    def test_post_with_malformed_row_shows_error(self) -> None:
        response = self._post('abc')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Строка выписки не найдена')
        self.assertFalse(TransferMoneyLog.objects.exists())

    def test_close_failure_rolls_back_transfer(self) -> None:
        with patch.object(
            BankStatementDecisionAudit.objects,
            'create',
            side_effect=RuntimeError('boom'),
        ):
            response = self._post(self.row.pk)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            str(constants.SUCCESS_MESSAGE_TRANSFER_MONEY),
        )
        self.assertFalse(TransferMoneyLog.objects.exists())
        self.debit.refresh_from_db()
        self.assertEqual(self.debit.balance, Decimal('1000.00'))
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
