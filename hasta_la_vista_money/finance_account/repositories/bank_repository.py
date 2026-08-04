import hashlib
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from hasta_la_vista_money.finance_account.models import Bank

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class BankRepository:
    def get_visible_banks(self, user: 'User') -> QuerySet[Bank]:
        return Bank.objects.filter(
            Q(is_system=True) | Q(user=user),
        ).order_by('name')

    def get_system_banks(self) -> QuerySet[Bank]:
        return Bank.objects.filter(is_system=True).order_by('name')

    def get_by_code(self, code: str) -> Bank | None:
        return Bank.objects.filter(code=code).first()

    def create_user_bank(
        self,
        user: 'User',
        name: str,
    ) -> Bank:
        code = self._generate_code(user.pk, name)
        return Bank.objects.create(
            code=code,
            name=name,
            is_system=False,
            user=user,
        )

    def get_by_name_and_user(
        self,
        name: str,
        user: 'User',
    ) -> Bank | None:
        normalized = name.strip()
        return Bank.objects.filter(
            Q(is_system=True) | Q(user=user),
            name__iexact=normalized,
        ).first()

    @staticmethod
    def _generate_code(user_pk: int, name: str) -> str:
        base = f'{user_pk}:{name.strip()}'
        hash_hex = hashlib.sha256(base.encode()).hexdigest()[:12]
        return f'user_{hash_hex}'
