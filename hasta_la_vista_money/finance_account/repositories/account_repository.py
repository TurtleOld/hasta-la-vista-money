"""Django репозиторий для Account модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class AccountRepository:
    """Репозиторий для работы с Account моделью."""

    def get_by_id(self, account_id: int) -> Account:
        """Получить account по ID."""
        return Account.objects.get(pk=account_id)

    def get_by_id_and_user(
        self,
        account_id: int,
        user: User,
    ) -> Account | None:
        """Получить account по ID и пользователю."""
        try:
            return Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return None

    def get_by_user(self, user: User) -> QuerySet[Account]:
        """Получить все accounts пользователя."""
        return Account.objects.by_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Account]:
        """Получить все accounts пользователя с select_related('user')."""
        return Account.objects.by_user_with_related(user)

    def get_by_user_and_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Account]:
        """Получить accounts пользователя или группы.

        Семантика параметра group_id:
        - 'my': только счета самого пользователя
        - None: все доступные счета (свои + из всех групп пользователя)
        - '123' (ID группы): счета всех пользователей из указанной группы

        Args:
            user: Пользователь, для которого получаем счета
            group_id: ID группы или 'my' для фильтрации, None для всех доступных

        Returns:
            QuerySet счетов в соответствии с фильтром
        """
        if group_id == 'my':
            return Account.objects.filter(user=user).select_related('user')

        if group_id is None:
            user_with_groups = User.objects.prefetch_related('groups').get(
                pk=user.pk,
            )
            user_groups = user_with_groups.groups.all()
            if user_groups.exists():
                users_in_groups = User.objects.filter(
                    groups__in=user_groups,
                ).distinct()
                return (
                    Account.objects.filter(user__in=users_in_groups)
                    .select_related('user')
                    .distinct()
                )
            return Account.objects.filter(user=user).select_related('user')

        users_in_group = User.objects.filter(groups__id=group_id).distinct()
        if users_in_group.exists():
            return (
                Account.objects.filter(user__in=users_in_group)
                .select_related('user')
                .distinct()
            )
        return Account.objects.filter(user=user).select_related('user')

    def get_credit_accounts(self) -> QuerySet[Account]:
        """Получить только кредитные счета и кредитные карты."""
        return Account.objects.credit()

    def get_debit_accounts(self) -> QuerySet[Account]:
        """Получить только дебетовые счета, дебетовые карты и наличные."""
        return Account.objects.debit()

    def get_by_currency(self, currency: str) -> QuerySet[Account]:
        """Получить accounts по валюте."""
        return Account.objects.by_currency(currency)

    def get_by_type(self, type_account: str) -> QuerySet[Account]:
        """Получить accounts по типу."""
        return Account.objects.by_type(type_account)

    def create_account(self, **kwargs: object) -> Account:
        """Создать новый account."""
        return Account.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Account]:
        """Фильтровать accounts."""
        return Account.objects.filter(**kwargs)

    def filter_with_select_related(
        self,
        *related_fields: str,
        **kwargs: object,
    ) -> QuerySet[Account]:
        """Фильтровать accounts с select_related."""
        return Account.objects.filter(**kwargs).select_related(*related_fields)
