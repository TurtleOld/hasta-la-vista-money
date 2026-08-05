from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.finance_account.models import Bank
from hasta_la_vista_money.finance_account.repositories.bank_repository import (
    BankRepository,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class BankService:
    def __init__(self, bank_repository: BankRepository) -> None:
        self.bank_repository = bank_repository

    def get_visible_banks(self, user: 'User') -> QuerySet[Bank]:
        return self.bank_repository.get_visible_banks(user)

    def get_or_create_user_bank(self, user: 'User', name: str) -> Bank:
        normalized = name.strip()
        if not normalized:
            raise ValidationError(
                _('Название банка не может быть пустым.'),
            )
        existing = self.bank_repository.get_by_name_and_user(
            normalized,
            user,
        )
        if existing is not None:
            return existing
        return self.bank_repository.create_user_bank(user, normalized)

    def get_by_code(self, code: str) -> Bank | None:
        return self.bank_repository.get_by_code(code)
