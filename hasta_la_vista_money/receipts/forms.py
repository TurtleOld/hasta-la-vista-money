import django_filters
from django.forms import (
    DecimalField,
    CharField,
    DateTimeInput,
    ModelForm,
    NumberInput,
    Select,
    TextInput,
    formset_factory,
    DateTimeField,
    ChoiceField,
)
from django.forms.fields import IntegerField
from django.utils.translation import gettext_lazy as _
from django_filters.fields import ModelChoiceField

from hasta_la_vista_money.commonlogic.forms import BaseFieldsForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    Receipt,
    Seller,
    OPERATION_TYPES,
)


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

    product_name = CharField(
        label='Наименование продукта',
        help_text='Укажите наименование продукта',
    )
    price = CharField(
        label='Цена продукта',
        help_text='Укажите цену продукта',
        widget=NumberInput(attrs={'class': 'price'}),
    )
    quantity = CharField(
        label='Количество продукта',
        help_text='Укажите количество продукта',
        widget=NumberInput(attrs={'class': 'quantity'}),
    )
    amount = CharField(
        label='Итоговая сумма за продукт',
        help_text='Высчитывается автоматически на основании цены и количества',
        widget=NumberInput(attrs={'class': 'amount', 'readonly': True}),
    )

    class Meta:
        model = Product
        fields = ['product_name', 'price', 'quantity', 'amount']

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

    seller = ModelChoiceField(
        queryset=Seller.objects.all(),
        label='Имя продавца',
        help_text='Выберите продавца. Если он ещё не создан, нажмите кнопку ниже.',
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label='Счёт списания',
        help_text='Выберите счёт списания. Если он ещё не создан, нажмите кнопку ниже.',
    )
    receipt_date = DateTimeField(
        label='Дата и время покупки',
        help_text='Указывается дата и время покупки, указанные в чеке.',
        widget=DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
        ),
    )
    operation_type = ChoiceField(
        choices=OPERATION_TYPES,
        label='Тип операции',
        help_text='Выберите тип операции.',
    )
    number_receipt = IntegerField(
        label='Номер документа',
        help_text='Укажите номер документа. Обычно на чеке указан как ФД.',
    )
    nds10 = DecimalField(
        label='НДС по ставке 10%',
        help_text='Поле необязательное',
        required=False,
    )
    nds20 = DecimalField(
        label='НДС по ставке 20%',
        help_text='Поле необязательное',
        required=False,
    )
    total_sum = DecimalField(
        label=_('Итоговая сумма по чеку'),
        help_text='Высчитывается автоматически на основании итоговых сумм продуктов',
        widget=NumberInput(
            attrs={'class': 'total-sum', 'readonly': True},
        ),
    )

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

    products = ProductFormSet()
