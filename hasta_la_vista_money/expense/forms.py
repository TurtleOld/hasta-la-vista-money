from django.forms import (
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
)
from django.forms.fields import CharField
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.custom_mixin import CategoryChoicesMixin
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account


class AddExpenseForm(ModelForm):
    category = ModelChoiceField(
        queryset=ExpenseCategory.objects.none(),
        label=_('Категория расхода'),
        help_text=_('Выберите категорию расхода'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт списания'),
        help_text=_('Выберите с какого счёта списывать расход'),
    )
    date = DateTimeField(
        label=_('Дата'),
        widget=DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
            },
        ),
        help_text=_('Укажите дату и время расхода'),
    )
    amount = DecimalField(
        label=_('Сумма списания'),
        help_text=_('Введите сумму списания'),
    )

    field = 'category'

    def __init__(self, *args, **kwargs):
        category_queryset = kwargs.pop('category_queryset', None)
        account_queryset = kwargs.pop('account_queryset', None)
        super().__init__(*args, **kwargs)
        if category_queryset is not None:
            self.fields['category'].queryset = category_queryset
        if account_queryset is not None:
            self.fields['account'].queryset = account_queryset

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    def clean(self):
        cleaned_data = super().clean()
        account_form = cleaned_data.get('account') if cleaned_data else None
        amount = cleaned_data.get('amount') if cleaned_data else None
        category = cleaned_data.get('category') if cleaned_data else None

        if account_form and amount and category:
            account = get_object_or_404(Account, id=account_form.id)
            if amount > account.balance:
                self.add_error('account', _(f'Недостаточно средств на счёте {account}'))
        return cleaned_data

    class Meta:
        model = Expense
        fields = ['category', 'account', 'date', 'amount']


class AddCategoryForm(CategoryChoicesMixin, ModelForm):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории расхода для её создания'),
    )
    parent_category = ModelChoiceField(
        queryset=ExpenseCategory.objects.none(),
        label=_('Родительская категория'),
        help_text=_(
            'Выберите родительскую категорию расхода для создаваемой категории'
        ),
        required=False,
        empty_label=_('Нет родительской категории'),
    )
    field = 'parent_category'

    def __init__(self, *args, **kwargs):
        category_queryset = kwargs.pop('category_queryset', None)
        super().__init__(*args, **kwargs)
        if category_queryset is not None:
            self.fields['parent_category'].queryset = category_queryset

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    def save(self, commit=True) -> ExpenseCategory:
        return super().save(commit=commit)

    class Meta:
        model = ExpenseCategory
        fields = ['name', 'parent_category']
