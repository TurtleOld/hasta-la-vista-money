"""Analytics currency: the one currency analytics pages show."""

from collections.abc import Iterable, Sequence

from hasta_la_vista_money.finance_account.currencies import (
    get_default_currency,
)
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
)
from hasta_la_vista_money.users.models import User


class AnalyticsCurrencyService:
    """Pick the analytics currency among the readable accounts."""

    def __init__(self, account_repository: AccountRepository) -> None:
        self.account_repository = account_repository

    def available_currencies(self, users: Iterable[User]) -> list[str]:
        return self.account_repository.get_currencies_by_users(users)

    def resolve(
        self,
        request_value: str | None,
        session_value: str | None,
        available: Sequence[str],
    ) -> str:
        default = get_default_currency()
        for value in (request_value, session_value, default):
            if value is not None and value in available:
                return value
        return available[0] if available else default
