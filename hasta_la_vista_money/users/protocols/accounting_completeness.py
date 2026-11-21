"""Protocol for independent accounting completeness assessment."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from hasta_la_vista_money.users.models import User
    from hasta_la_vista_money.users.protocols.statement_balance_verification import (  # noqa: E501
        StatementBalanceVerificationServiceProtocol,
    )
    from hasta_la_vista_money.users.services.accounting_completeness import (
        AccountingCompletenessResult,
        BalanceBlockProjection,
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
        balance_provider: (
            StatementBalanceVerificationServiceProtocol | None
        ) = None,
    ) -> AccountingCompletenessResult: ...

    def balance_block(
        self,
        *,
        owner: User,
        account_ids: Sequence[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        provider: StatementBalanceVerificationServiceProtocol | None = None,
    ) -> BalanceBlockProjection: ...
