import django_filters
from django.forms import (
    CharField,
    DateTimeInput,
    ModelForm,
    NumberInput,
    Select,
    TextInput,
    formset_factory,
)
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.commonlogic.forms import BaseFieldsForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller


class ReceiptFilter(django_filters.FilterSet):
    """Класс представляющий фильтр чеков на сайте."""

    name_seller = django_filters.ModelChoiceFilter(
        queryset=Seller.objects.all(),
        field_name='seller__name_seller',
        label=_('Продавец'),
        widget=Select(attrs={'class': 'form-control mb-2'}),
    )
    receipt_date = django_filters.DateFromToRangeFilter(
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
        self.filters['name_seller'].queryset = (
            Seller.objects.filter(user=self.user)
            .distinct('name_seller')
            .order_by('name_seller')
        )
        self.filters['account'].queryset = Account.objects.filter(
            user=self.user,
        )

    @property
    def qs(self):
        queryset = super().qs
        return queryset.filter(user=self.user).distinct()

    class Meta:
        model = Receipt
        fields = ['name_seller', 'receipt_date', 'account']


class SellerForm(ModelForm):
    """Класс формы продавца."""

    name_seller = CharField(label='Имя продавца')
    retail_place_address = CharField(
        label='Адрес места покупки',
        widget=TextInput(attrs={'placeholder': 'Поле может быть пустым'}),
    )
    retail_place = CharField(
        label='Название магазина',
        widget=TextInput(attrs={'placeholder': 'Поле может быть пустым'}),
    )

    class Meta:
        model = Seller
        fields = ['name_seller', 'retail_place_address', 'retail_place']

    def __init__(self, *args, **kwargs):
        """
        Конструктов класса инициализирующий поля формы.

        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)
        self.fields['retail_place_address'].required = False
        self.fields['retail_place'].required = False


class ProductForm(BaseFieldsForm):
    """Форма для внесения данных по продуктам."""

    labels = {
        'product_name': _('Наименование продукта'),
        'price': _('Цена'),
        'quantity': _('Количество'),
        'amount': _('Сумма'),
    }

    class Meta:
        model = Product
        fields = ['product_name', 'price', 'quantity', 'amount']
        widgets = {
            'price': NumberInput(attrs={'class': 'price'}),
            'quantity': NumberInput(attrs={'class': 'quantity'}),
            'amount': NumberInput(attrs={'class': 'amount', 'readonly': True}),
        }

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        if quantity <= 0:
            self.add_error(
                'quantity',
                _('Количество должно быть больше 0.'),
            )
        return cleaned_data


ProductFormSet = formset_factory(ProductForm, extra=1)


class ReceiptForm(BaseFieldsForm):
    """Форма для внесения данных по чеку."""

    labels = {
        'seller': _('Имя продавца'),
        'account': _('Счёт'),
        'receipt_date': _('Дата и время чека'),
        'operation_type': _('Тип операции'),
        'number_receipt': _('Номер документа'),
        'nds10': _('НДС 10%'),
        'nds20': _('НДС 20%'),
        'total_sum': _('Итоговая сумма по чеку'),
    }

    class Meta:
        model = Receipt
        fields = [
            'seller',
            'account',
            'receipt_date',
            'number_receipt',
            'operation_type',
            'total_sum',
        ]
        widgets = {
            'receipt_date': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
            ),
            'total_sum': NumberInput(
                attrs={'class': 'total-sum', 'readonly': True},
            ),
        }

    products = ProductFormSet()
