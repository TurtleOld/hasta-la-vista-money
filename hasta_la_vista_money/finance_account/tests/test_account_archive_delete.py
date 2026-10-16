"""Archiving and deleting an account share one rule for web and API."""

from decimal import Decimal
from typing import cast
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.factories import (
    AccountFactory,
    TransferMoneyLogFactory,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.loan.models import Loan
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_feed import list_operations
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import BankStatementUpload, User

ACCOUNT_LABEL = 'finance_account.Account'


class AccountArchiveDeleteBase(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.other = cast('User', UserFactory())
        self.account = cast(
            'Account',
            AccountFactory(user=self.user, balance=Decimal('0.00')),
        )
        self.service = ApplicationContainer().finance_account.account_service()
        self.client.force_login(self.user)

    def _reload(self, account: Account) -> Account:
        account.refresh_from_db()
        return account

    def _add_transaction(self, account: Account) -> None:
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=account,
            category=Category.objects.create(
                user=self.user,
                name='Еда',
                type=TransactionType.EXPENSE,
            ),
            amount=Decimal('10.00'),
            date=timezone.now(),
        )


class ArchiveAccountTests(AccountArchiveDeleteBase):
    def _archive_url(self, account: Account) -> str:
        return reverse('finance_account:archive', args=[account.pk])

    def _unarchive_url(self, account: Account) -> str:
        return reverse('finance_account:unarchive', args=[account.pk])

    def test_zero_balance_account_goes_to_archive_and_back(self) -> None:
        self.client.post(self._archive_url(self.account))
        self.assertTrue(self._reload(self.account).is_archived)

        self.client.post(self._unarchive_url(self.account))
        self.assertFalse(self._reload(self.account).is_archived)

    def test_nonzero_balance_is_refused_with_adjustment_hint(self) -> None:
        self.account.balance = Decimal('5.00')
        self.account.save()

        response = self.client.post(
            self._archive_url(self.account),
            follow=True,
        )

        self.assertFalse(self._reload(self.account).is_archived)
        self.assertContains(response, 'корректировк')

    def test_archived_account_keeps_history_and_leaves_selection(self) -> None:
        self._add_transaction(self.account)
        self.client.post(self._archive_url(self.account))

        self.assertTrue(
            Transaction.objects.filter(account=self.account).exists(),
        )
        self.assertFalse(
            Account.objects.available_for_operations()
            .filter(pk=self.account.pk)
            .exists(),
        )

    def test_deposit_account_is_refused(self) -> None:
        deposit = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            balance=Decimal('0.00'),
            currency='RUB',
            bank=self.account.bank,
        )

        with self.assertRaises(ValidationError):
            self.service.archive_account(
                user=self.user,
                account_id=deposit.pk,
            )
        self.assertFalse(self._reload(deposit).is_archived)

    def test_foreign_account_is_404(self) -> None:
        foreign = cast('Account', AccountFactory(user=self.other))

        response = self.client.post(self._archive_url(foreign))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self._reload(foreign).is_archived)

    def test_service_rejects_foreign_account(self) -> None:
        foreign = cast('Account', AccountFactory(user=self.other))

        with self.assertRaises(PermissionDenied):
            self.service.archive_account(
                user=self.user,
                account_id=foreign.pk,
            )

    def test_audit_names_account_archiving(self) -> None:
        self.client.post(self._archive_url(self.account))

        log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(self.account.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertEqual(log.kind, AuditOperationKind.ACCOUNT_EDIT)
        self.assertIn('archived_at', log.diff['changed'])
        page = list_operations(
            AuditLog.objects.filter(object_pk=str(self.account.pk)),
            page=1,
            page_size=10,
        )
        self.assertEqual(page.operations[0].title, 'Архивация счёта')


class DeleteAccountTests(AccountArchiveDeleteBase):
    def _web_delete(self, account: Account):  # type: ignore[no-untyped-def]
        return self.client.post(
            reverse('finance_account:delete_account', args=[account.pk]),
            follow=True,
        )

    def _api_url(self, account: Account) -> str:
        return reverse('finance_account:api_detail', kwargs={'pk': account.pk})

    def _api_client(self) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client

    def _make_transfer_only(self) -> TransferMoneyLog:
        return cast(
            'TransferMoneyLog',
            TransferMoneyLogFactory(
                user=self.user,
                from_account=self.account,
                to_account=AccountFactory(user=self.user),
            ),
        )

    def test_account_without_movements_is_deleted_in_web(self) -> None:
        self._web_delete(self.account)
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())

    def test_account_without_movements_is_deleted_via_api(self) -> None:
        response = self._api_client().delete(self._api_url(self.account))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())

    def test_account_with_transfer_only_is_kept_with_both_sides(self) -> None:
        transfer = self._make_transfer_only()

        self._web_delete(self.account)

        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())
        transfer.refresh_from_db()
        self.assertEqual(transfer.from_account_id, self.account.pk)
        self.assertIsNotNone(transfer.to_account_id)

    def test_account_with_movements_is_refused_in_web(self) -> None:
        self._add_transaction(self.account)

        response = self._web_delete(self.account)

        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())
        self.assertContains(response, constants.ACCOUNT_HAS_MOVEMENTS_MESSAGE)

    def test_account_with_movements_gets_409_via_api(self) -> None:
        self._add_transaction(self.account)

        response = self._api_client().delete(self._api_url(self.account))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'],
            str(constants.ACCOUNT_HAS_MOVEMENTS_MESSAGE),
        )
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())

    def test_account_with_statement_upload_is_refused(self) -> None:
        BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statements/a.pdf',
        )

        response = self._api_client().delete(self._api_url(self.account))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())

    def test_account_with_loan_is_refused(self) -> None:
        Loan.objects.create(
            user=self.user,
            account=self.account,
            date=timezone.now(),
            loan_amount=Decimal('1000.00'),
            annual_interest_rate=Decimal('10.00'),
            period_loan=12,
        )

        response = self._api_client().delete(self._api_url(self.account))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())

    def test_protected_error_is_reported_as_movements_refusal(self) -> None:
        self._add_transaction(self.account)

        with (
            mock.patch.object(Account, 'has_movements', return_value=False),
            self.assertRaises(ValidationError),
        ):
            self.service.delete_account(
                user=self.user,
                account_id=self.account.pk,
            )
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())

    def test_foreign_account_is_404(self) -> None:
        foreign = cast('Account', AccountFactory(user=self.other))

        self.assertEqual(self._web_delete(foreign).status_code, 404)
        self.assertEqual(
            self._api_client().delete(self._api_url(foreign)).status_code,
            404,
        )
        self.assertTrue(Account.objects.filter(pk=foreign.pk).exists())

    def test_deposit_account_is_not_deleted(self) -> None:
        deposit = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            balance=Decimal('0.00'),
            currency='RUB',
            bank=self.account.bank,
        )

        self.assertEqual(self._web_delete(deposit).status_code, 404)
        self.assertEqual(
            self._api_client().delete(self._api_url(deposit)).status_code,
            404,
        )
        with self.assertRaises(ValidationError):
            self.service.delete_account(user=self.user, account_id=deposit.pk)
        self.assertTrue(Account.objects.filter(pk=deposit.pk).exists())

    def test_delete_is_audited_as_account_delete(self) -> None:
        pk = self.account.pk
        self._web_delete(self.account)

        log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(pk),
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(log.kind, AuditOperationKind.ACCOUNT_DELETE)
