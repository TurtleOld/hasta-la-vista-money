from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.receipts.validators.product_line import (
    ProductLineError,
    check_product_line,
)
from hasta_la_vista_money.users.models import User


class ProductLineRuleTests(SimpleTestCase):
    """One receipt line rule shared by every intake path."""

    def _check(
        self,
        price: str,
        quantity: str,
        amount: str,
    ) -> ProductLineError | None:
        return check_product_line(
            price=Decimal(price),
            quantity=Decimal(quantity),
            amount=Decimal(amount),
        )

    def test_accepts_paid_line(self) -> None:
        self.assertIsNone(self._check('10.00', '2', '20.00'))

    def test_accepts_free_line(self) -> None:
        self.assertIsNone(self._check('0.00', '1', '0.00'))

    def test_tolerates_one_kopeck_rounding(self) -> None:
        self.assertIsNone(self._check('33.33', '3', '100.00'))

    def test_skips_amount_cross_check_for_weighed_goods(self) -> None:
        self.assertIsNone(self._check('199.90', '0.35', '69.77'))

    def test_rejects_negative_price(self) -> None:
        self.assertEqual(
            self._check('-1.00', '1', '0.00'),
            ProductLineError.NEGATIVE_PRICE,
        )

    def test_rejects_non_positive_quantity(self) -> None:
        self.assertEqual(
            self._check('10.00', '0', '0.00'),
            ProductLineError.NON_POSITIVE_QUANTITY,
        )

    def test_rejects_negative_amount(self) -> None:
        self.assertEqual(
            self._check('0.00', '1', '-1.00'),
            ProductLineError.NEGATIVE_AMOUNT,
        )

    def test_rejects_amount_mismatch_for_piece_goods(self) -> None:
        self.assertEqual(
            self._check('10.00', '2', '25.00'),
            ProductLineError.AMOUNT_MISMATCH,
        )


class ReceiptCreatorFreeItemTests(TestCase):
    """FNS receipts may contain free lines such as a gift or a bag."""

    def test_creates_receipt_with_free_line(self) -> None:
        user = User.objects.create_user(
            username='creator-free-item-user',
            password='pass',  # nosec B106: test-only password
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )
        service = ApplicationContainer().receipts.receipt_creator_service()

        receipt = service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=timezone.now(),
                total_sum=Decimal('10.00'),
                operation_type=1,
            ),
            seller_data=SellerCreateData(name_seller='Shop'),
            products_data=[
                {
                    'product_name': 'Кефир',
                    'category': 'Прочее',
                    'price': '10.00',
                    'quantity': '1',
                    'amount': '10.00',
                },
                {
                    'product_name': 'Пакет-подарок',
                    'category': 'Прочее',
                    'price': '0.00',
                    'quantity': '1',
                    'amount': '0.00',
                },
            ],
            allow_insufficient_funds=True,
        )

        free_line = receipt.product.get(product_name='Пакет-подарок')
        self.assertEqual(free_line.amount, Decimal('0.00'))
        self.assertEqual(receipt.product.count(), 2)

    def test_rejects_negative_line_with_its_name(self) -> None:
        user = User.objects.create_user(
            username='creator-negative-item-user',
            password='pass',  # nosec B106: test-only password
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )
        service = ApplicationContainer().receipts.receipt_creator_service()

        with self.assertRaisesMessage(ValueError, "'Скидка'"):
            service.create_receipt_with_products(
                user=user,
                account=account,
                receipt_data=ReceiptCreateData(
                    receipt_date=timezone.now(),
                    total_sum=Decimal('10.00'),
                    operation_type=1,
                ),
                seller_data=SellerCreateData(name_seller='Shop'),
                products_data=[
                    {
                        'product_name': 'Скидка',
                        'category': 'Прочее',
                        'price': '-5.00',
                        'quantity': '1',
                        'amount': '-5.00',
                    },
                ],
                allow_insufficient_funds=True,
            )
