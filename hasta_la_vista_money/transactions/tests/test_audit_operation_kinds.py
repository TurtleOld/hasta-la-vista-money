"""Each TransactionService action gives an audit operation of its own kind."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.transactions.commands import (
    CreateTransactionCommand,
    UpdateTransactionCommand,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.transactions.repositories.transaction_repository import (  # noqa: E501
    TransactionRepository,
)
from hasta_la_vista_money.transactions.services.transaction_ops import (
    TransactionService,
)
from hasta_la_vista_money.users.models import User

TRANSACTION_LABEL = 'transactions.Transaction'
ACCOUNT_LABEL = 'finance_account.Account'


def _operations_for(transaction_obj: Transaction) -> list[UUID | None]:
    logs = AuditLog.objects.filter(
        model_name=TRANSACTION_LABEL,
        object_pk=str(transaction_obj.pk),
    )
    return list(logs.values_list('operation_id', flat=True).distinct())


class TransactionAuditOperationKindTests(TestCase):
    fixtures = ['users.yaml', 'finance_account.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.account.user = self.user
        self.account.balance = Decimal('1000.00')
        self.account.save()

        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )

        container = ApplicationContainer()
        self.service = TransactionService(
            account_service=container.core.account_service(),
            transaction_repository=TransactionRepository(),
        )

    def test_add_income_gives_one_income_operation(self) -> None:
        transaction_obj = self.service.add_transaction(
            CreateTransactionCommand(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('500.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            ),
        )

        operation_ids = _operations_for(transaction_obj)
        self.assertEqual(len(operation_ids), 1)
        logs = AuditLog.objects.filter(operation_id=operation_ids[0])
        self.assertTrue(logs.exists())
        for log in logs:
            self.assertEqual(log.kind, AuditOperationKind.INCOME)

        self.assertTrue(
            AuditLog.objects.filter(
                model_name=ACCOUNT_LABEL,
                object_pk=str(self.account.pk),
                operation_id=operation_ids[0],
            ).exists(),
        )

    def test_add_expense_gives_one_expense_operation(self) -> None:
        transaction_obj = self.service.add_transaction(
            CreateTransactionCommand(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('300.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            ),
        )

        operation_ids = _operations_for(transaction_obj)
        self.assertEqual(len(operation_ids), 1)
        for log in AuditLog.objects.filter(operation_id=operation_ids[0]):
            self.assertEqual(log.kind, AuditOperationKind.EXPENSE)

    def test_update_transaction_gives_one_edit_operation(self) -> None:
        transaction_obj = self.service.add_transaction(
            CreateTransactionCommand(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('300.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            ),
        )

        updated = self.service.update_transaction(
            UpdateTransactionCommand(
                user=self.user,
                transaction_obj=transaction_obj,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('350.00'),
                transaction_date=date(2026, 4, 2),
                type_value=TransactionType.EXPENSE,
            ),
        )

        logs = AuditLog.objects.filter(
            model_name=TRANSACTION_LABEL,
            object_pk=str(updated.pk),
            action=AuditLog.Action.UPDATE,
        )
        operation_ids = set(logs.values_list('operation_id', flat=True))
        self.assertEqual(len(operation_ids), 1)
        for log in logs:
            self.assertEqual(log.kind, AuditOperationKind.TRANSACTION_EDIT)

    def test_delete_transaction_gives_one_delete_operation(self) -> None:
        transaction_obj = self.service.add_transaction(
            CreateTransactionCommand(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('300.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            ),
        )
        transaction_pk = transaction_obj.pk

        self.service.delete_transaction(
            user=self.user,
            transaction_obj=transaction_obj,
        )

        logs = AuditLog.objects.filter(
            model_name=TRANSACTION_LABEL,
            object_pk=str(transaction_pk),
            action=AuditLog.Action.DELETE,
        )
        operation_ids = set(logs.values_list('operation_id', flat=True))
        self.assertEqual(len(operation_ids), 1)
        for log in logs:
            self.assertEqual(log.kind, AuditOperationKind.TRANSACTION_DELETE)
