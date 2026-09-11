"""Each finance_account action gives an audit operation of its own kind."""

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    from django.contrib.auth import get_user_model

    UserType = get_user_model()

ACCOUNT_LABEL = 'finance_account.Account'
TRANSFER_LABEL = 'finance_account.TransferMoneyLog'


class TransferAuditOperationKindTests(TestCase):
    def setUp(self) -> None:
        self.user: UserType = cast('UserType', UserFactory())
        self.container = ApplicationContainer()
        self.transfer_service = (
            self.container.finance_account.transfer_service()
        )
        self.from_account: Account = cast(
            'Account',
            AccountFactory(user=self.user, balance=Decimal('1000.00')),
        )
        self.to_account: Account = cast(
            'Account',
            AccountFactory(user=self.user, balance=Decimal('500.00')),
        )

    def test_transfer_gives_one_transfer_operation_covering_both_balances(
        self,
    ) -> None:
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )

        log = AuditLog.objects.get(
            model_name=TRANSFER_LABEL,
            object_pk=str(transfer_log.pk),
        )
        self.assertEqual(log.kind, AuditOperationKind.TRANSFER)
        operation_id = log.operation_id
        self.assertIsNotNone(operation_id)

        group = AuditLog.objects.filter(operation_id=operation_id)
        self.assertTrue(
            group.filter(
                model_name=ACCOUNT_LABEL,
                object_pk=str(self.from_account.pk),
            ).exists(),
        )
        self.assertTrue(
            group.filter(
                model_name=ACCOUNT_LABEL,
                object_pk=str(self.to_account.pk),
            ).exists(),
        )
        for entry in group:
            self.assertEqual(entry.kind, AuditOperationKind.TRANSFER)

    def test_delete_transfer_gives_one_transfer_operation(self) -> None:
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )
        transfer_pk = transfer_log.pk

        self.transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )

        delete_log = AuditLog.objects.get(
            model_name=TRANSFER_LABEL,
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(delete_log.kind, AuditOperationKind.TRANSFER)
        group = AuditLog.objects.filter(operation_id=delete_log.operation_id)
        for entry in group:
            self.assertEqual(entry.kind, AuditOperationKind.TRANSFER)


class AccountAuditOperationKindTests(TestCase):
    def setUp(self) -> None:
        self.user: UserType = cast('UserType', UserFactory())
        self.account: Account = cast('Account', AccountFactory(user=self.user))

    def test_create_account_gives_one_account_edit_operation(self) -> None:
        self.client.force_login(self.user)
        url = reverse('finance_account:create')
        data = {
            'name_account': 'Новый счёт',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }

        self.client.post(url, data, follow=True)

        account = Account.objects.get(
            user=self.user,
            name_account='Новый счёт',
        )
        log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account.pk),
            action=AuditLog.Action.CREATE,
        )
        self.assertEqual(log.kind, AuditOperationKind.ACCOUNT_EDIT)

    def test_change_account_gives_one_account_edit_operation(self) -> None:
        self.client.force_login(self.user)
        url = reverse('finance_account:change', args=[self.account.pk])
        data = {
            'name_account': 'Переименованный счёт',
            'type_account': 'Debit',
            'balance': self.account.balance,
            'currency': self.account.currency,
        }

        self.client.post(url, data, follow=True)

        logs = AuditLog.objects.filter(
            model_name=ACCOUNT_LABEL,
            object_pk=str(self.account.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertTrue(logs.exists())
        operation_ids = set(logs.values_list('operation_id', flat=True))
        self.assertEqual(len(operation_ids), 1)
        for log in logs:
            self.assertEqual(log.kind, AuditOperationKind.ACCOUNT_EDIT)

    def test_delete_account_gives_one_account_delete_operation(self) -> None:
        self.client.force_login(self.user)
        account_pk = self.account.pk
        url = reverse('finance_account:delete_account', args=[account_pk])

        self.client.post(url, follow=True)

        logs = list(
            AuditLog.objects.filter(
                model_name=ACCOUNT_LABEL,
                object_pk=str(account_pk),
                action=AuditLog.Action.DELETE,
            ),
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].kind, AuditOperationKind.ACCOUNT_DELETE)
