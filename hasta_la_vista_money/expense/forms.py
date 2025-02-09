from django.forms import DateTimeInput, ModelChoiceField
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.commonlogic.forms import BaseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account


class AddExpenseForm(BaseForm):
    labels = {
        'category': _('Категория расхода'),
        'account': _('Счёт списания'),
        'date': _('Дата'),
        'amount': _('Сумма'),
    }

    category = ModelChoiceField(queryset=ExpenseCategory.objects.all())

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
        widgets = {
            'date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
        }


class AddCategoryForm(BaseForm):
    labels = {
        'name': _('Название категории'),
        'parent_category': _('Вложенность'),
    }
    field = 'parent_category'

    def configure_category_choices(self, category_choices):
        self.fields[self.field].choices = category_choices

    class Meta:
        model = ExpenseCategory
        fields = ['name', 'parent_category']
