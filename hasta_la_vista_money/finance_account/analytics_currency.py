"""View helper for the analytics currency switcher."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.http import HttpRequest

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.finance_account.services import (
        AnalyticsCurrencyServiceProtocol,
    )


@dataclass(frozen=True)
class AnalyticsCurrency:
    """Selected analytics currency and the switcher choices."""

    currency: str
    currencies: list[str]


def get_analytics_currency(
    request: HttpRequest,
    users: Iterable[User],
    *,
    remember: bool = True,
) -> AnalyticsCurrency:
    """Read ``?currency=``, remember the choice in the session.

    Put the result into the context as ``analytics_currency`` and include
    ``includes/analytics_currency_switcher.html``. Saves pass
    ``remember=False`` so that only page views change the choice.
    """
    service: AnalyticsCurrencyServiceProtocol = cast(
        'RequestWithContainer',
        request,
    ).container.finance_account.analytics_currency_service()
    currencies = service.available_currencies(users)
    key = constants.ANALYTICS_CURRENCY_SESSION_KEY
    requested = request.GET.get(constants.ANALYTICS_CURRENCY_PARAM)
    stored = request.session.get(key)
    currency = service.resolve(requested, stored, currencies)
    if remember and requested == currency:
        request.session[key] = currency
    elif remember and stored is not None and stored not in currencies:
        del request.session[key]
    return AnalyticsCurrency(currency=currency, currencies=currencies)
