from django.forms import DateTimeInput, ModelChoiceField, DateTimeField, DecimalField
from django.forms.fields import CharField
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.commonlogic.forms import BaseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account


class AddExpenseForm(BaseForm):
    category = ModelChoiceField(
        queryset=ExpenseCategory.objects.all(),
        label=_('Категория расхода'),
        help_text=_('Выберите категорию расхода'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label=_('Счёт списания'),
        help_text=_('Выберите с какого счёта списывать расход'),
    )
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            }
        ),
        help_text=_('Укажите дату и время расхода'),
    )
    amount = DecimalField(
        label=_('Сумма списания'),
        help_text=_('Введите сумму списания'),
    )

    field = 'category'

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    def clean(self):
        cleaned_data = super().clean()
        account_form = cleaned_data.get('account')
        amount = cleaned_data.get('amount')
        category = cleaned_data.get('category')

        if account_form and amount and category:
            account = get_object_or_404(Account, id=account_form.id)
            if amount > account.balance:
                self.add_error(
                    'account',
                    _(f'Недостаточно средств на счёте {account}'),
                )
        return cleaned_data

    class Meta:
        model = Expense
        fields = ['category', 'account', 'date', 'amount']


class AddCategoryForm(BaseForm):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории расхода для её создания'),
    )
    parent_category = ModelChoiceField(
        queryset=ExpenseCategory.objects.all(),
        label=_('Родительская категория'),
        help_text=_(
            'Выберите родительскую категорию расхода для создаваемой категории'
        ),
    )
    field = 'parent_category'

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    class Meta:
        model = ExpenseCategory
        fields = ['name', 'parent_category']
