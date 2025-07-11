from typing import Type


class IncomeFormQuerysetMixin:
    """
    Mixin to provide category and account querysets for income forms based on the current user.
    Subclasses must define category_model and account_model attributes.
    """

    category_model: Type
    account_model: Type

    def get_category_queryset(self):
        user = self.request.user  # type: ignore[attr-defined]
        return self.category_model.objects.filter(user=user)

    def get_account_queryset(self):
        user = self.request.user  # type: ignore[attr-defined]
        return self.account_model.objects.filter(user=user)
