import django_filters
from django.forms import Select
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _
from django_filters import widgets
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account


class ExpenseFilter(django_filters.FilterSet):
    category = django_filters.ModelChoiceFilter(
        queryset=ExpenseCategory.objects.all(),
        field_name='category',
        label=_('Категория'),
        widget=Select(attrs={'class': 'form-control mb-2'}),
    )
    date = django_filters.DateFromToRangeFilter(
        label=_('Период'),
        widget=widgets.RangeWidget(
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
            ExpenseCategory.objects.filter(user=self.user).distinct().order_by('name')
        )
        self.filters['account'].queryset = Account.objects.filter(
            user=self.user,
        )

    @property
    def qs(self):
        """Возвращает QuerySet с фильтрацией по пользователю."""
        queryset = super().qs
        return queryset.filter(user=self.user).distinct()

    def get_expenses_with_annotations(self):
        """Возвращает список расходов с дополнительными полями для отображения."""
        queryset = self.qs
        expenses = queryset.values(
            'id',
            'date',
            'account__name_account',
            'category__name',
            'category__parent_category__name',
            'amount',
            'user',
        )

        # Добавляем date_label для каждого расхода
        expense_list = []
        for expense in expenses:
            expense_dict = dict(expense)
            if expense['date']:
                expense_dict['date_label'] = date_format(expense['date'], 'd.m.Y H:i')
                expense_dict['date_month'] = expense['date']
            else:
                expense_dict['date_label'] = ''
                expense_dict['date_month'] = None

            user_obj = queryset.model.objects.get(id=expense['id']).user
            expense_dict['user'] = user_obj

            expense_list.append(expense_dict)

        return expense_list

    class Meta:
        model = Expense
        fields = ['category', 'date', 'account']
