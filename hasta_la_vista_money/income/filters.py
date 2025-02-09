import django_filters
from django.forms import Select
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeFilter(django_filters.FilterSet):
    category = django_filters.ModelChoiceFilter(
        queryset=IncomeCategory.objects.all(),
        field_name='category',
        label=_('Категория'),
        widget=Select(attrs={'class': 'form-control mb-2'}),
    )
    date = django_filters.DateFromToRangeFilter(
        label=_('Период'),
        widget=django_filters.widgets.RangeWidget(
            attrs={
                'class': 'form-control',
                'type': 'date',
            },
        ),
    )
    account = django_filters.ModelChoiceFilter(
        queryset=Account.objects.all(),
        label=_('Счёт'),
        widget=Select(attrs={'class': 'form-control mb-4'}),
    )

    def __init__(self, *args, **kwargs):
        """
        Конструктор класса инициализирующий поля формы.

        :param args:
        :param kwargs:
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.filters['category'].queryset = (
            IncomeCategory.objects.filter(user=self.user).distinct().order_by('name')
        )
        self.filters['account'].queryset = Account.objects.filter(
            user=self.user,
        )

    @property
    def qs(self):
        queryset = super().qs
        return (
            queryset.filter(user=self.user)
            .distinct()
            .values(
                'id',
                'date',
                'account__name_account',
                'category__name',
                'category__parent_category__name',
                'amount',
            )
        )

    class Meta:
        model = Income
        fields = ['category', 'date', 'account']
