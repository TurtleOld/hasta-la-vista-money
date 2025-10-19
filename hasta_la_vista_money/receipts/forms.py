from os.path import splitext

import django_filters
from django.core.exceptions import ValidationError
from django.db.models import Min
from django.forms import (
    CharField,
    ChoiceField,
    ClearableFileInput,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    FileField,
    Form,
    ModelForm,
    NumberInput,
    Select,
    TextInput,
    formset_factory,
)
from django.forms.fields import IntegerField
from django.utils.translation import gettext_lazy as _
from django_filters.fields import ModelChoiceField
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    OPERATION_TYPES,
    Product,
    Receipt,
    Seller,
)


class ReceiptFilter(django_filters.FilterSet):
    name_seller = django_filters.ModelChoiceFilter(
        queryset=Seller.objects.all(),
        field_name='seller__name_seller',
        label='',
        widget=Select(attrs={'class': 'form-control mb-2'}),
    )
    receipt_date = django_filters.DateFromToRangeFilter(
        label='',
        widget=django_filters.widgets.RangeWidget(
            attrs={
                'class': 'form-control',
                'type': 'date',
            },
        ),
    )
    account = django_filters.ModelChoiceFilter(
        queryset=Account.objects.all(),
        label='',
        widget=Select(attrs={'class': 'form-control mb-4'}),
    )
    total_sum_min = django_filters.NumberFilter(
        field_name='total_sum',
        lookup_expr='gte',
        label='',
        widget=NumberInput(
            attrs={'class': 'form-control', 'placeholder': _('Сумма от')},
        ),
    )
    total_sum_max = django_filters.NumberFilter(
        field_name='total_sum',
        lookup_expr='lte',
        label='',
        widget=NumberInput(
            attrs={'class': 'form-control', 'placeholder': _('Сумма до')},
        ),
    )
    product_name = django_filters.CharFilter(
        method='filter_by_product_name',
        label='',
        widget=TextInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': _('Введите товар'),
            },
        ),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        seller_ids = (
            Seller.objects.filter(user=self.user)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values_list('min_id', flat=True)
        )
        self.filters['name_seller'].queryset = Seller.objects.filter(pk__in=seller_ids)

        self.filters['account'].queryset = (
            Account.objects.filter(user=self.user)
            .select_related('user')
            .only('id', 'name_account', 'user__id')
        )

    @property
    def qs(self):
        queryset = super().qs
        return (
            queryset.select_related('seller', 'account', 'user')
            .prefetch_related('product')
            .distinct()
        )

    def filter_by_product_name(self, queryset, name, value):
        if value:
            return queryset.filter(product__product_name__icontains=value)
        return queryset

    class Meta:
        model = Receipt
        fields = [
            'name_seller',
            'receipt_date',
            'account',
            'total_sum_min',
            'total_sum_max',
            'product_name',
        ]


class SellerForm(ModelForm[Seller]):
    name_seller = CharField(label=_('Имя продавца'))
    retail_place_address = CharField(
        label=_('Адрес места покупки'),
        widget=TextInput(attrs={'placeholder': _('Поле может быть пустым')}),
    )
    retail_place = CharField(
        label=_('Название магазина'),
        widget=TextInput(attrs={'placeholder': _('Поле может быть пустым')}),
    )

    class Meta:
        model = Seller
        fields = ['name_seller', 'retail_place_address', 'retail_place']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['retail_place_address'].required = False
        self.fields['retail_place'].required = False


class ProductForm(ModelForm[Product]):
    product_name = CharField(
        label=_('Наименование продукта'),
        help_text=_('Укажите наименование продукта'),
    )
    price = DecimalField(
        label=_('Цена продукта'),
        help_text=_('Укажите цену продукта'),
        widget=NumberInput(attrs={'class': 'price'}),
    )
    quantity = DecimalField(
        label=_('Количество продукта'),
        help_text=_('Укажите количество продукта'),
        widget=NumberInput(attrs={'class': 'quantity', 'step': '0.01'}),
        max_digits=10,
        decimal_places=2,
    )
    amount = DecimalField(
        label=_('Итоговая сумма за продукт'),
        help_text=_('Высчитывается автоматически на основании цены и количества'),
        widget=NumberInput(attrs={'class': 'amount', 'readonly': True}),
    )

    class Meta:
        model = Product
        fields = ['product_name', 'price', 'quantity', 'amount']

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        if quantity is not None and quantity <= 0:
            self.add_error(
                'quantity',
                _('Количество должно быть больше 0.'),
            )
        return cleaned_data


ProductFormSet = formset_factory(ProductForm, extra=1, can_delete=True)


class ReceiptForm(ModelForm[Receipt]):
    seller = ModelChoiceField(
        queryset=Seller.objects.all(),
        label=_('Имя продавца'),
        help_text=_('Выберите продавца. Если он ещё не создан, нажмите кнопку ниже.'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label=_('Счёт списания'),
        help_text=_(
            'Выберите счёт списания. Если он ещё не создан, нажмите кнопку ниже.',
        ),
    )
    receipt_date = DateTimeField(
        label=_('Дата и время покупки'),
        help_text=_('Указывается дата и время покупки, указанные в чеке.'),
        widget=DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
        ),
    )
    operation_type = ChoiceField(
        choices=OPERATION_TYPES,
        label=_('Тип операции'),
        help_text=_('Выберите тип операции.'),
    )
    number_receipt = IntegerField(
        label=_('Номер документа'),
        help_text=_('Укажите номер документа. Обычно на чеке указан как ФД.'),
    )
    nds10 = DecimalField(
        label=_('НДС по ставке 10%'),
        help_text=_('Поле необязательное'),
        required=False,
    )
    nds20 = DecimalField(
        label=_('НДС по ставке 20%'),
        help_text=_('Поле необязательное'),
        required=False,
    )
    total_sum = DecimalField(
        label=_('Итоговая сумма по чеку'),
        help_text=_('Высчитывается автоматически на основании итоговых сумм продуктов'),
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
            'nds10',
            'nds20',
            'total_sum',
        ]

    products = ProductFormSet()


def validate_image_jpg_png(value):
    ext = splitext(value.name)[1].lower()

    if ext not in ['.jpg', '.jpeg', '.png']:
        raise ValidationError(_('Разрешены только файлы форматов: JPG, JPEG или PNG'))


class UploadImageForm(Form):
    account = ModelChoiceField(
        label=_('Счёт'),
        queryset=Account.objects.all(),
        widget=Select(attrs={'class': 'form-control'}),
    )
    file = FileField(
        label=_('Выберите файл'),
        widget=ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.jpg,.jpeg,.png',
                'data-max-size': '5242880',
            },
        ),
        validators=[validate_image_jpg_png],
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(user=user)
        if self.fields['account'].queryset.exists():
            self.fields['account'].initial = self.fields['account'].queryset.first()

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if file.size > 5 * 1024 * 1024:
                raise ValidationError(_('Размер файла не должен превышать 5MB'))
        return file
