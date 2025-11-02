from typing import Any


class IncomeFormQuerysetMixin:
    """
    Mixin to provide category and account querysets for income forms
    based on the current user.
    Subclasses must define category_model and account_model attributes.
    """

    category_model: type
    account_model: type

    def get_category_queryset(self) -> Any:
        user = self.request.user  # type: ignore[attr-defined]
        return self.category_model.objects.filter(user=user)  # type: ignore[attr-defined]

    def get_account_queryset(self) -> Any:
        user = self.request.user  # type: ignore[attr-defined]
        return self.account_model.objects.filter(user=user)  # type: ignore[attr-defined]
