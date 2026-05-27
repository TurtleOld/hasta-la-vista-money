"""django-filter FilterSet for the unified Transaction list."""

from typing import Any, ClassVar

import django_filters
from django.forms import Select
from django_filters.widgets import RangeWidget

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)

FORM_CONTROL_CLASS = (
    'w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm '
    'text-gray-900 shadow-sm transition-colors duration-200 '
    'placeholder:text-gray-400 focus:border-green-500 focus:outline-none '
    'focus:ring-2 focus:ring-green-500/30 dark:border-gray-600 '
    'dark:bg-gray-700 dark:text-white dark:placeholder:text-gray-400'
)


class TransactionFilter(django_filters.FilterSet):
    """Filter transactions by type, category, account, and date range."""

    type = django_filters.ChoiceFilter(
        choices=TransactionType.choices,
        label='',
        widget=Select(attrs={'class': f'{FORM_CONTROL_CLASS} mb-2'}),
    )
    category = django_filters.ModelChoiceFilter(
        queryset=Category.objects.all(),
        field_name='category',
        label='',
        widget=Select(attrs={'class': f'{FORM_CONTROL_CLASS} mb-2'}),
    )
    date = django_filters.DateFromToRangeFilter(
        label='',
        widget=RangeWidget(
            attrs={
                'class': FORM_CONTROL_CLASS,
                'type': 'date',
            },
        ),
    )
    account = django_filters.ModelChoiceFilter(
        queryset=Account.objects.all(),
        label='',
        widget=Select(attrs={'class': f'{FORM_CONTROL_CLASS} mb-4'}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.user = kwargs.pop('user', None)
        self.users = kwargs.pop('users', None)
        super().__init__(*args, **kwargs)
        users = self.users or [self.user]
        self.filters['category'].queryset = (  # type: ignore[attr-defined]
            Category.objects.filter(user__in=users).distinct().order_by('name')
        )
        self.filters['account'].queryset = Account.objects.filter(  # type: ignore[attr-defined]
            user__in=users,
        )

    @property
    def qs(self) -> Any:
        """Restrict the queryset to the configured user(s)."""
        queryset = super().qs
        users = self.users or [self.user]
        return (
            queryset.filter(user__in=users)
            .distinct()
            .values(
                'id',
                'type',
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
        model = Transaction
        fields: ClassVar[list[str]] = ['type', 'category', 'date', 'account']
