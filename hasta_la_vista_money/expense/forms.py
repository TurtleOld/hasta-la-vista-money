from typing import Any, ClassVar

from django.db.models import QuerySet
from django.forms import (
    CharField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelChoiceField,
    ModelForm,
)
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.custom_mixin import (
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    FormQuerysetsMixin,
)
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account


class AddExpenseForm(FormQuerysetsMixin, ModelForm[Expense]):
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

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[ExpenseCategory] | None = None,
        account_queryset: QuerySet[Account] | None = None,
        **kwargs: Any,
    ) -> None:
        if 'category_queryset' in kwargs:
            category_queryset = kwargs.pop('category_queryset')
        if 'account_queryset' in kwargs:
            account_queryset = kwargs.pop('account_queryset')
        super().__init__(
            *args,
            category_queryset=category_queryset,
            account_queryset=account_queryset,
            **kwargs,
        )

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if not cleaned_data:
            return {}
        account_form = cleaned_data.get('account')
        amount = cleaned_data.get('amount')
        category = cleaned_data.get('category')

        if account_form and amount and category:
            account = get_object_or_404(Account, pk=account_form.pk)
            if amount > account.balance:
                self.add_error(
                    'account',
                    _(f'Недостаточно средств на счёте {account}'),
                )
        return cleaned_data

    class Meta:
        model = Expense
        fields: ClassVar[list[str]] = ['category', 'account', 'date', 'amount']


class AddCategoryForm(
    CategoryChoicesConfigurerMixin,
    CategoryChoicesMixin,
    ModelForm[ExpenseCategory],
):
    name = CharField(
        label=_('Название категории'),
        help_text=_('Введите название категории расхода для её создания'),
    )
    parent_category = ModelChoiceField[ExpenseCategory](
        queryset=ExpenseCategory.objects.none(),
        label=_('Родительская категория'),
        help_text=_(
            'Выберите родительскую категорию расхода для создаваемой категории',
        ),
        required=False,
        empty_label=_('Нет родительской категории'),
    )
    field = 'parent_category'

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[ExpenseCategory] | None = None,
        **kwargs: Any,
    ) -> None:
        """Инициализирует queryset для поля 'parent_category'."""
        if 'category_queryset' in kwargs:
            category_queryset = kwargs.pop('category_queryset')
        super().__init__(*args, category_queryset=category_queryset, **kwargs)

    def save(self, commit: bool = True) -> ExpenseCategory:
        return super().save(commit=commit)

    class Meta:
        model = ExpenseCategory
        fields: ClassVar[list[str]] = ['name', 'parent_category']
