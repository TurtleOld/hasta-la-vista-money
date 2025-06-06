from os.path import splitext
import django_filters
from django.core.exceptions import ValidationError
from django.forms import (
    CharField,
    ChoiceField,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    ModelForm,
    NumberInput,
    Select,
    TextInput,
    formset_factory,
    Form,
    FileField, ClearableFileInput,
)
from django.forms.fields import IntegerField
from django.utils.translation import gettext_lazy as _
from django_filters.fields import ModelChoiceField
from hasta_la_vista_money.commonlogic.forms import BaseFieldsForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    OPERATION_TYPES,
    Product,
    Receipt,
    Seller,
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
        label=_('Наименование продукта'),
        help_text=_('Укажите наименование продукта'),
    )
    price = DecimalField(
        label=_('Цена продукта'),
        help_text=_('Укажите цену продукта'),
        widget=NumberInput(attrs={'class': 'price'}),
    )
    quantity = IntegerField(
        label=_('Количество продукта'),
        help_text=_('Укажите количество продукта'),
        widget=NumberInput(attrs={'class': 'quantity'}),
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
        label=_('Имя продавца'),
        help_text=_('Выберите продавца. Если он ещё не создан, нажмите кнопку ниже.'),
    )
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        label=_('Счёт списания'),
        help_text=_(
            'Выберите счёт списания. Если он ещё не создан, нажмите кнопку ниже.'
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
            'total_sum',
        ]

    products = ProductFormSet()


def validate_image_jpg_png(value):
    ext = splitext(value.name)[1].lower()

    if ext not in ['.jpg', '.jpeg', '.png']:
        raise ValidationError(_('Разрешены только файлы форматов: JPG, JPEG или PNG'))


class UploadImageForm(Form):
    account = ModelChoiceField(
        queryset=Account.objects.all(),
        widget=Select(attrs={'class': 'form-control'}),
    )
    file = FileField(
        label='Выберите файл',
        widget=ClearableFileInput(attrs={
            'class': 'form-control',
        }),
        validators=[validate_image_jpg_png],
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].initial = Account.objects.filter(user=user)
