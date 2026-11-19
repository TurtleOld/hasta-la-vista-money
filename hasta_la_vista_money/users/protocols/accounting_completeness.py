"""Protocol for independent accounting completeness assessment."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from hasta_la_vista_money.users.models import User
    from hasta_la_vista_money.users.services.accounting_completeness import (
        AccountingCompletenessResult,
    )


@runtime_checkable
class AccountingCompletenessServiceProtocol(Protocol):
    """Coverage, processing proof and problem summary for selected dates."""

    def assess(
        self,
        *,
        owner: User,
        account_ids: Sequence[int] | None = None,
        period_start: date,
        period_end: date,
        balance_provider: object | None = None,
    ) -> AccountingCompletenessResult: ...
