from typing import Any, ClassVar

import django_filters
from django.forms import Select
from django_filters.widgets import RangeWidget

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeFilter(django_filters.FilterSet):
    category = django_filters.ModelChoiceFilter(
        queryset=IncomeCategory.objects.all(),
        field_name='category',
        label='',
        widget=Select(attrs={'class': 'form-control mb-2'}),
    )
    date = django_filters.DateFromToRangeFilter(
        label='',
        widget=RangeWidget(
            attrs={
                'class': 'form-control',
                'type': 'date',
            },
        ),
    )
    account = django_filters.ModelChoiceFilter(
        queryset=Account.objects.all(),
        label='',
        widget=Select(attrs={'class': 'form-control mb-4'}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize filter fields for the current user.
        """
        self.user = kwargs.pop('user', None)
        self.users = kwargs.pop('users', None)
        super().__init__(*args, **kwargs)
        users = self.users or [self.user]
        self.filters['category'].queryset = (  # type: ignore[attr-defined]
            IncomeCategory.objects.filter(user__in=users)
            .distinct()
            .order_by('name')
        )
        self.filters['account'].queryset = Account.objects.filter(  # type: ignore[attr-defined]
            user__in=users,
        )

    @property
    def qs(self) -> Any:
        """Get the queryset of incomes for the current user."""
        queryset = super().qs
        users = self.users or [self.user]
        return (
            queryset.filter(user__in=users)
            .distinct()
            .values(
                'id',
                'date',
                'account__name_account',
                'category__name',
                'category__parent_category__name',
                'amount',
                'user__id',
                'user__username',
            )
        )

    class Meta:
        model = Income
        fields: ClassVar[list[str]] = ['category', 'date', 'account']
