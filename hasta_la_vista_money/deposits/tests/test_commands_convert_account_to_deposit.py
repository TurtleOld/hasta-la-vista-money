from datetime import date
from decimal import Decimal
from io import StringIO
from typing import TYPE_CHECKING, cast

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEPOSIT
from hasta_la_vista_money.deposits.models import Deposit, DepositPrincipalEvent
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class ConvertAccountToDepositCommandTests(TestCase):
    def _create_production_account(self, user: 'User') -> Account:
        return Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('75000.00'),
        )

    def _call(self, account_id: int, *, dry_run: bool = False) -> str:
        out = StringIO()
        call_command(
            'convert_account_to_deposit',
            f'--account-id={account_id}',
            '--name=Production вклад',
            '--bank=SBERBANK',
            '--opened-on=2026-06-01',
            '--matures-on=2026-12-01',
            '--annual-rate=14.00',
            '--converted-on=2026-08-01',
            '--dry-run' if dry_run else '--no-dry-run',
            stdout=out,
        )
        return out.getvalue()

    def test_dry_run_makes_no_changes(self) -> None:
        user = cast('User', UserFactory())
        account = self._create_production_account(user)

        output = self._call(account.pk, dry_run=True)

        account.refresh_from_db()
        self.assertEqual(account.type_account, 'Debit')
        self.assertFalse(Deposit.objects.filter(account=account).exists())
        self.assertIn(str(account.pk), output)
        self.assertIn('Debit', output)
        self.assertIn('75000.00', output)
        self.assertIn('RUB', output)

    def test_successful_run_converts_account(self) -> None:
        user = cast('User', UserFactory())
        account = self._create_production_account(user)

        self._call(account.pk, dry_run=False)

        account.refresh_from_db()
        self.assertEqual(account.type_account, ACCOUNT_TYPE_DEPOSIT)
        self.assertEqual(account.balance, Decimal('75000.00'))
        deposit = Deposit.objects.get(account=account)
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(event.effective_on, date(2026, 8, 1))
        self.assertEqual(event.amount, Decimal('75000.00'))

    def test_repeat_run_does_not_duplicate(self) -> None:
        user = cast('User', UserFactory())
        account = self._create_production_account(user)
        self._call(account.pk, dry_run=False)

        with self.assertRaises(CommandError):
            self._call(account.pk, dry_run=False)

        self.assertEqual(Deposit.objects.filter(account=account).count(), 1)
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(
                deposit__account=account,
            ).count(),
            1,
        )

    def test_rejects_unknown_account(self) -> None:
        with self.assertRaises(CommandError):
            self._call(999999, dry_run=False)

    def test_rejects_account_already_of_deposit_type(self) -> None:
        user = cast('User', UserFactory())
        account = self._create_production_account(user)
        self._call(account.pk, dry_run=False)
        account.refresh_from_db()
        self.assertEqual(account.type_account, ACCOUNT_TYPE_DEPOSIT)

        with self.assertRaises(CommandError):
            self._call(account.pk, dry_run=False)
