from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ScanQRForm, UploadImageForm
from hasta_la_vista_money.receipts.models import Receipt

if TYPE_CHECKING:
    from datetime import datetime

    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

FORMS = (ScanQRForm, UploadImageForm)


class UploadFormsDefaultAccountTests(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user = UserType.objects.get(pk=1)
        self.card = Account.objects.get(pk=1)
        self.main = Account.objects.get(pk=2)

    def _receipt(
        self,
        account: Account,
        receipt_date: 'datetime | None' = None,
    ) -> Receipt:
        return Receipt.objects.create(
            user=account.user,
            account=account,
            receipt_date=receipt_date or timezone.now(),
            operation_type=constants.RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('100.00'),
        )

    def _assert_initial(self, user: 'UserType', expected: Account) -> None:
        for form_class in FORMS:
            with self.subTest(form=form_class.__name__):
                form = form_class(user=user)
                self.assertEqual(form.fields['account'].initial, expected)

    def test_preselects_account_of_last_created_receipt(self) -> None:
        self._receipt(self.card)
        self._receipt(
            self.main,
            receipt_date=timezone.now() - timedelta(days=365),
        )

        self._assert_initial(self.user, self.main)

    def test_falls_back_when_last_account_unavailable(self) -> None:
        self._receipt(self.main)
        self.main.archived_at = timezone.now()
        self.main.save(update_fields=['archived_at'])

        self._assert_initial(self.user, self.card)

    def test_skips_deposit_account_of_last_receipt(self) -> None:
        deposit = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        self._receipt(self.main)
        self._receipt(deposit)

        self._assert_initial(self.user, self.card)

    def test_falls_back_to_first_account_without_receipts(self) -> None:
        self._assert_initial(self.user, self.card)

    def test_ignores_other_users_receipts(self) -> None:
        self._receipt(self.main)
        other_user = UserType.objects.get(pk=2)
        other_account = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            currency='RUB',
            balance=Decimal('100.00'),
        )
        self._receipt(other_account)

        self._assert_initial(self.user, self.main)
