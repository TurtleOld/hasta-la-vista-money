"""Each receipt action gives an audit operation of its own kind."""

from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse_lazy

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    ProductCategory,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.repositories import ProductCategoryRepository
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

RECEIPT_LABEL = 'receipts.Receipt'
ACCOUNT_LABEL = 'finance_account.Account'


def _seed_starter_product_categories(user: 'UserType') -> None:
    ProductCategoryRepository().seed_starter_categories(user)


class ReceiptAuditOperationKindTests(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'receipt_receipt.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = UserType.objects.get(pk=1)
        _seed_starter_product_categories(self.user)
        self.account = Account.objects.get(pk=1)
        self.receipt = Receipt.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)
        self.client.force_login(self.user)

    def test_create_receipt_gives_one_receipt_purchase_operation(self) -> None:
        new_seller = Seller.objects.create(
            user=self.user,
            name_seller='ООО Рога и Копыта',
        )
        category = ProductCategory.objects.get(
            user=self.user,
            name='Прочее',
        )

        form_data = {
            'seller': new_seller.pk,
            'account': self.account.pk,
            'receipt_date': '2023-06-28 21:24',
            'number_receipt': 111,
            'operation_type': 1,
            'total_sum': 10,
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 0,
            'form-MIN_NUM_FORMS': 0,
            'form-MAX_NUM_FORMS': 1000,
            'form-0-product_name': 'Яблоко',
            'form-0-category': category.pk,
            'form-0-price': 10,
            'form-0-quantity': 1,
            'form-0-amount': 10,
            'form-0-nds_type': 1,
            'form-0-nds_sum': 1.3,
        }

        self.client.post(reverse_lazy('receipts:create'), data=form_data)

        receipt = Receipt.objects.get(
            user=self.user,
            seller=new_seller,
            number_receipt=111,
        )
        create_logs = AuditLog.objects.filter(
            model_name=RECEIPT_LABEL,
            object_pk=str(receipt.pk),
            action=AuditLog.Action.CREATE,
        )
        self.assertEqual(create_logs.count(), 1)
        create_log = create_logs.get()
        operation_id = create_log.operation_id
        self.assertIsNotNone(operation_id)
        self.assertEqual(
            create_log.kind,
            AuditOperationKind.RECEIPT_PURCHASE,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                model_name=ACCOUNT_LABEL,
                object_pk=str(self.account.pk),
                operation_id=operation_id,
            ).exists(),
        )

    def test_update_receipt_gives_one_receipt_edit_operation(self) -> None:
        update_data = {
            'seller': self.seller.pk,
            'account': self.account.pk,
            'receipt_date': self.receipt.receipt_date.strftime(
                '%Y-%m-%d %H:%M:%S',
            ),
            'number_receipt': self.receipt.number_receipt,
            'operation_type': 1,
            'total_sum': '999.00',
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 0,
            'form-MIN_NUM_FORMS': 0,
            'form-MAX_NUM_FORMS': 1000,
            'form-0-product_name': 'Новый товар',
            'form-0-price': '999.00',
            'form-0-quantity': 1,
            'form-0-amount': '999.00',
        }

        self.client.post(
            reverse_lazy('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        logs = AuditLog.objects.filter(
            model_name=RECEIPT_LABEL,
            object_pk=str(self.receipt.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertTrue(logs.exists())
        operation_ids = set(logs.values_list('operation_id', flat=True))
        self.assertEqual(len(operation_ids), 1)
        for log in logs:
            self.assertEqual(log.kind, AuditOperationKind.RECEIPT_EDIT)

    def test_delete_receipt_gives_one_receipt_delete_operation(self) -> None:
        receipt_pk = self.receipt.pk

        self.client.post(
            reverse_lazy('receipts:delete', kwargs={'pk': receipt_pk}),
            follow=True,
        )

        logs = AuditLog.objects.filter(
            model_name=RECEIPT_LABEL,
            object_pk=str(receipt_pk),
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.get().kind, AuditOperationKind.RECEIPT_DELETE)
