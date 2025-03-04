from django.forms import (
    DateTimeInput,
    ModelChoiceField,
    DateTimeField,
    DecimalField,
    CharField,
)
from hasta_la_vista_money.commonlogic.forms import BaseForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory


class IncomeForm(BaseForm):
    """Модельная форма отображения доходов на сайте."""

    category = ModelChoiceField(
        queryset=IncomeCategory.objects.all(),
        label='Категория дохода',
        help_text='Выберите категорию дохода',
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label='Счёт списания',
        help_text='Выберите на какой счёт зачислить доход',
    )
    date = DateTimeField(
        label='Дата',
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            }
        ),
        help_text='Укажите дату и время получения дохода',
    )
    amount = DecimalField(
        label='Сумма пополнения',
        help_text='Введите сумму пополнения',
    )

    field = 'category'

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    class Meta:
        model = Income
        fields = ['category', 'account', 'date', 'amount']
        widgets = {
            'date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }


class AddCategoryIncomeForm(BaseForm):
    name = CharField(
        label='Название категории',
        help_text='Введите название категории дохода для её создания',
    )
    parent_category = ModelChoiceField(
        queryset=IncomeCategory.objects.all(),
        label='Родительская категория',
        help_text='Выберите родительскую категорию дохода для создаваемой категории',
    )
    field = 'parent_category'

    class Meta:
        model = IncomeCategory
        fields = ['name', 'parent_category']

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices
