from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog

User = get_user_model()


class AuditLogTests(TestCase):
    def test_audit_log_created_for_financial_model_create(self) -> None:
        user = User.objects.create_user(username='audit-user')

        account = Account.objects.create(user=user, balance=Decimal('100.00'))

        audit_log = AuditLog.objects.get(
            model_name='finance_account.Account',
            object_pk=str(account.pk),
            action=AuditLog.Action.CREATE,
        )
        self.assertEqual(audit_log.user, user)
        self.assertEqual(audit_log.object_name, account.name_account)
        self.assertEqual(audit_log.diff['created']['Баланс'], '100.00')

    def test_audit_log_created_for_financial_model_update(self) -> None:
        user = User.objects.create_user(username='audit-user')
        account = Account.objects.create(user=user, balance=Decimal('100.00'))

        account.balance = Decimal('75.50')
        account.save()

        audit_log = AuditLog.objects.get(
            model_name='finance_account.Account',
            object_pk=str(account.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertEqual(
            audit_log.diff['Баланс'],
            {'old': '100.00', 'new': '75.50'},
        )

    def test_audit_log_created_for_financial_model_delete(self) -> None:
        user = User.objects.create_user(username='audit-user')
        account = Account.objects.create(user=user, balance=Decimal('100.00'))
        object_pk = str(account.pk)

        account.delete()

        audit_log = AuditLog.objects.get(
            model_name='finance_account.Account',
            object_pk=object_pk,
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(audit_log.user, user)
        self.assertEqual(audit_log.diff['deleted']['Баланс'], '100.00')
