"""Posts a loan payment: debits the source and reduces the loan debt."""

from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
    AccountRepository,
)
from hasta_la_vista_money.loan.models import PaymentMakeLoan
from hasta_la_vista_money.loan.repositories import (
    LoanRepository,
    PaymentMakeLoanRepository,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.users.models import User


class LoanPaymentService:
    """Turns a loan payment into one atomic balance movement."""

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        account_repository: AccountRepository,
        loan_repository: LoanRepository,
        payment_repository: PaymentMakeLoanRepository,
    ) -> None:
        self.account_service = account_service
        self.account_repository = account_repository
        self.loan_repository = loan_repository
        self.payment_repository = payment_repository

    def post_payment(
        self,
        *,
        user: User,
        loan_id: int,
        account_id: int | None,
        amount: Decimal,
        date: datetime,
    ) -> PaymentMakeLoan:
        """Return the posted payment.

        A ``None`` source is external: only the loan account changes.
        The payment may not exceed the remaining debt.
        """
        if amount <= 0:
            raise ValidationError(_('Сумма платежа должна быть больше нуля.'))
        loan = self.loan_repository.filter(pk=loan_id, user=user).first()
        if loan is None:
            raise PermissionDenied(_('У вас нет прав на этот кредит.'))
        source = None
        if account_id is not None:
            source = self.account_repository.get_by_id_and_user(
                account_id,
                user,
            )
            if source is None:
                raise PermissionDenied(_('У вас нет прав на этот счёт.'))

            if source.is_deposit:
                raise ValidationError(
                    _('Платёж со вклада недоступен.'),
                )

        # The loan money is spent from its account, a payment returns it.
        deltas = {loan.account_id: amount}
        if source is not None:
            deltas[source.pk] = -amount
        with (
            db_transaction.atomic(),
            audit_operation(
                kind=AuditOperationKind.LOAN_PAYMENT,
            ),
        ):
            balance = self.account_repository.get_by_ids_for_update(
                {loan.account_id},
            )[loan.account_id].balance
            if amount > loan.loan_amount - balance:
                raise ValidationError(
                    _('Сумма платежа больше остатка долга по кредиту.'),
                )
            self.account_service.apply_account_deltas(deltas)
            return self.payment_repository.create_payment(
                user=user,
                account=source,
                loan=loan,
                date=date,
                amount=amount,
                is_posted=True,
            )
