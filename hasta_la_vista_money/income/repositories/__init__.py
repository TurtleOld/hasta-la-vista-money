"""Репозитории для income модуля."""

from hasta_la_vista_money.income.repositories.income_category_repository import (  # noqa: E501
    IncomeCategoryRepository,
)
from hasta_la_vista_money.income.repositories.income_repository import (
    IncomeRepository,
)

__all__ = [
    'IncomeCategoryRepository',
    'IncomeRepository',
]
