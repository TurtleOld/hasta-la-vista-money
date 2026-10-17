"""Admin не должен обходить сервис остатков: деньги только для чтения."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

TEST_PASSWORD = 'pwd123456!'  # nosec B105


class AdminReadOnlyMoneyTest(TestCase):
    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username='root',
            password=TEST_PASSWORD,
        )
        self.client.force_login(self.admin_user)
        self.user = User.objects.create_user(
            username='owner',
            password=TEST_PASSWORD,
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
            balance=Decimal(1000),
            currency='RUB',
        )
        self.other = Account.objects.create(
            user=self.user,
            name_account='Other',
            balance=Decimal(500),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )

    def _post(self, name: str, obj_id: int, data: dict[str, object]) -> None:
        url = reverse(f'admin:{name}_change', args=[obj_id])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

    def test_transaction_money_fields_are_read_only(self) -> None:
        tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal(100),
            date=timezone.now(),
            description='old',
        )
        self._post(
            'transactions_transaction',
            tx.pk,
            {
                'user': self.user.pk,
                'account': self.other.pk,
                'category': self.category.pk,
                'type': TransactionType.INCOME,
                'amount': '999',
                'date_0': '2026-01-01',
                'date_1': '10:00:00',
                'description': 'new',
                'source_ref': '',
            },
        )
        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal(100))
        self.assertEqual(tx.account_id, self.account.pk)
        self.assertEqual(tx.type, TransactionType.EXPENSE)
        self.assertEqual(tx.description, 'new')

    def test_transaction_add_and_delete_are_forbidden(self) -> None:
        tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal(100),
            date=timezone.now(),
        )
        add = self.client.get(reverse('admin:transactions_transaction_add'))
        self.assertEqual(add.status_code, 403)
        delete = self.client.post(
            reverse('admin:transactions_transaction_delete', args=[tx.pk]),
            {'post': 'yes'},
        )
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Transaction.objects.filter(pk=tx.pk).exists())

    def test_receipt_money_fields_and_delete(self) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        product = Product.objects.create(
            user=self.user,
            product_name='Milk',
            price=10,
            quantity=1,
            amount=10,
        )
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now(),
            total_sum=Decimal(100),
            operation_type=1,
        )
        receipt.product.add(product)
        self._post(
            'receipts_receipt',
            receipt.pk,
            {
                'user': self.user.pk,
                'account': self.other.pk,
                'seller': seller.pk,
                'number_receipt': 1,
                'product': [product.pk],
                'receipt_date_0': '2026-01-01',
                'receipt_date_1': '10:00:00',
                'total_sum': '999',
                'operation_type': 2,
                'requires_attention': 'on',
            },
        )
        receipt.refresh_from_db()
        self.assertEqual(receipt.total_sum, Decimal(100))
        self.assertEqual(receipt.account_id, self.account.pk)
        self.assertEqual(receipt.operation_type, 1)
        self.assertTrue(receipt.requires_attention)
        self.assertEqual(
            self.client.get(reverse('admin:receipts_receipt_add')).status_code,
            403,
        )
        delete = self.client.post(
            reverse('admin:receipts_receipt_delete', args=[receipt.pk]),
            {'post': 'yes'},
        )
        self.assertEqual(delete.status_code, 403)

    def test_transfer_money_fields_and_delete(self) -> None:
        log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other,
            amount=Decimal(50),
            exchange_date=timezone.now(),
            notes='old',
        )
        self._post(
            'finance_account_transfermoneylog',
            log.pk,
            {
                'user': self.user.pk,
                'from_account': self.other.pk,
                'to_account': self.account.pk,
                'amount': '999',
                'exchange_date_0': '2026-01-01',
                'exchange_date_1': '10:00:00',
                'notes': 'new',
            },
        )
        log.refresh_from_db()
        self.assertEqual(log.amount, Decimal(50))
        self.assertEqual(log.from_account_id, self.account.pk)
        self.assertEqual(log.notes, 'new')
        self.assertEqual(
            self.client.get(
                reverse('admin:finance_account_transfermoneylog_add'),
            ).status_code,
            403,
        )
        delete = self.client.post(
            reverse(
                'admin:finance_account_transfermoneylog_delete',
                args=[log.pk],
            ),
            {'post': 'yes'},
        )
        self.assertEqual(delete.status_code, 403)

    def test_account_balance_and_currency_are_read_only(self) -> None:
        self._post(
            'finance_account_account',
            self.account.pk,
            {
                'user': self.user.pk,
                'name_account': 'Renamed',
                'bank': self.account.bank_id,
                'type_account': self.account.type_account,
                'balance': '1',
                'currency': 'USD',
            },
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal(1000))
        self.assertEqual(self.account.currency, 'RUB')
        self.assertEqual(self.account.name_account, 'Renamed')

    def test_account_with_movements_cannot_be_deleted(self) -> None:
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal(100),
            date=timezone.now(),
        )
        delete = self.client.post(
            reverse(
                'admin:finance_account_account_delete',
                args=[self.account.pk],
            ),
            {'post': 'yes'},
        )
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())
