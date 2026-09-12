"""Behavioral invariant: an account's balance history is an unbroken chain.

Every write to ``Account.balance`` goes through a normal ``save()`` call, so
each audit entry's "new" value must equal the next entry's "old" value, and
the last entry's "new" value must equal the account's current balance. This
is verified by running real actions, not by scanning the source for
``.update()`` calls.
"""

from decimal import Decimal
from itertools import pairwise
from typing import Any

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.finance_account.services.transfer_service import (
    TransferService,
)
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.users.models import User

ACCOUNT_LABEL = 'finance_account.Account'


def _balance_movements(account_id: int) -> list[tuple[Decimal, Decimal]]:
    """Return the (old, new) balance pairs from an account's audit history.

    Only entries that actually touch ``balance`` are returned, in the order
    they were written — matching the order real actions happened in.
    """
    logs = AuditLog.objects.filter(
        model_name=ACCOUNT_LABEL,
        object_pk=str(account_id),
    ).order_by('pk')

    movements: list[tuple[Decimal, Decimal]] = []
    for log in logs:
        diff: dict[str, Any] = log.diff
        if log.action == AuditLog.Action.CREATE:
            created = diff.get('created', {})
            if 'balance' in created:
                opening = Decimal(created['balance'])
                movements.append((opening, opening))
            continue
        changed = diff.get('changed', {})
        if 'balance' in changed:
            old = Decimal(changed['balance']['old'])
            new = Decimal(changed['balance']['new'])
            movements.append((old, new))
    return movements


class BalanceChainContinuityTests(TestCase):
    """Real actions on an account keep an unbroken before/after chain."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='chain-user')
        self.other_user_account = Account.objects.create(
            user=self.user,
            name_account='Второй счёт',
            balance=Decimal('0.00'),
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('1000.00'),
        )
        self.balance_service = BalanceService()
        self.account_repository = AccountRepository()
        self.transfer_service = TransferService(
            transfer_money_log_repository=TransferMoneyLogRepository(),
        )

    def test_chain_survives_a_realistic_sequence_of_actions(self) -> None:
        # A real deposit-of-funds style movement.
        self.balance_service.apply_balance_delta(
            self.account,
            Decimal('250.00'),
        )
        # A real transfer to another account and back.
        self.transfer_service.transfer_money(
            from_account=self.account,
            to_account=self.other_user_account,
            amount=Decimal('300.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )
        # A real archive/unarchive round trip, as deposit closure performs.
        self.account_repository.archive(self.account.pk)
        self.account_repository.unarchive(self.account.pk)
        # One more real spend.
        self.balance_service.apply_receipt_spend(self.account, Decimal('75.00'))

        movements = _balance_movements(self.account.pk)
        self.assertGreaterEqual(len(movements), 3)

        for previous, current in pairwise(movements):
            self.assertEqual(
                previous[1],
                current[0],
                'Каждое "было" должно совпадать с предыдущим "стало".',
            )

        self.account.refresh_from_db(fields=['balance'])
        self.assertEqual(movements[-1][1], self.account.balance)

    def test_archive_and_unarchive_leave_no_balance_entry(self) -> None:
        """Archiving does not touch balance, so it stays out of the chain."""
        self.account_repository.archive(self.account.pk)
        self.account_repository.unarchive(self.account.pk)

        archive_logs = AuditLog.objects.filter(
            model_name=ACCOUNT_LABEL,
            object_pk=str(self.account.pk),
            action=AuditLog.Action.UPDATE,
        ).order_by('pk')

        self.assertEqual(archive_logs.count(), 2)
        for log in archive_logs:
            self.assertIn('archived_at', log.diff['changed'])
            self.assertNotIn('balance', log.diff['changed'])
