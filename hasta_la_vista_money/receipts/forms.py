from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import django_filters
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Min, Q, QuerySet
from django.forms import (
    CharField,
    ChoiceField,
    ClearableFileInput,
    DateTimeField,
    DateTimeInput,
    DecimalField,
    FileField,
    Form,
    ModelChoiceField,
    ModelForm,
    NumberInput,
    Select,
    TextInput,
    formset_factory,
)
from django.forms.fields import IntegerField
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_filters import widgets

if TYPE_CHECKING:
    from django.forms.formsets import BaseFormSet as BaseFormSetType

    from hasta_la_vista_money.users.models import User
else:
    User = get_user_model()

from hasta_la_vista_money import constants
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
        widget=widgets.RangeWidget(
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
    product_names = django_filters.CharFilter(
        method='filter_by_product_names',
        label='',
        widget=TextInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': _('Введите товар'),
            },
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        seller_ids = (
            Seller.objects.filter(user=self.user)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values_list('min_id', flat=True)
        )
        self.filters['name_seller'].queryset = Seller.objects.filter(  # type: ignore[attr-defined]
            pk__in=seller_ids,
        )

        self.filters['account'].queryset = (  # type: ignore[attr-defined]
            Account.objects.filter(user=self.user)
            .select_related('user')
            .only('id', 'name_account', 'user__id')
        )

    @property
    def qs(self) -> Any:
        queryset = super().qs
        return (
            queryset.select_related('seller', 'account', 'user')
            .prefetch_related('product')
            .distinct()
        )

    def filter_by_product_names(
        self,
        queryset: QuerySet[Receipt],
        field_name: str,
        value: str,
    ) -> QuerySet[Receipt]:
        """Фильтрация чеков по нескольким наименованиям товаров.

        Args:
            queryset: QuerySet чеков для фильтрации.
            field_name: Имя поля (не используется).
            value: Строка с названиями товаров, разделенными запятой.

        Returns:
            QuerySet[Receipt]: Отфильтрованный QuerySet чеков.
        """
        if not value:
            return queryset

        product_names = [
            name.strip() for name in value.split(',') if name.strip()
        ]

        if not product_names:
            return queryset

        q_objects = Q()

        for product_name in product_names:
            q_objects |= Q(product__product_name__icontains=product_name)

        return queryset.filter(q_objects).distinct()

    class Meta:
        model = Receipt
        fields: ClassVar[list[str]] = [
            'name_seller',
            'receipt_date',
            'account',
            'total_sum_min',
            'total_sum_max',
            'product_names',
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
        fields: ClassVar[list[str]] = [
            'name_seller',
            'retail_place_address',
            'retail_place',
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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
        widget=NumberInput(
            attrs={
                'class': 'quantity',
                'step': str(constants.QUANTITY_STEP),
            },
        ),
        max_digits=constants.MAX_DIGITS_DECIMAL_FIELD,
        decimal_places=constants.DECIMAL_PLACES_PRECISION,
    )
    amount = DecimalField(
        label=_('Итоговая сумма за продукт'),
        help_text=_(
            'Высчитывается автоматически на основании цены и количества',
        ),
        widget=NumberInput(attrs={'class': 'amount', 'readonly': True}),
    )

    class Meta:
        model = Product
        fields: ClassVar[list[str]] = [
            'product_name',
            'price',
            'quantity',
            'amount',
        ]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data is None:
            cleaned_data = {}
        quantity = cleaned_data.get('quantity')
        if quantity is not None and quantity <= constants.ZERO:
            self.add_error(
                'quantity',
                _('Количество должно быть больше 0.'),
            )
        return cleaned_data


_ProductFormSet = formset_factory(
    ProductForm,
    extra=constants.FORMSET_EXTRA_DEFAULT,
    can_delete=True,
)

if TYPE_CHECKING:
    ProductFormSetType = type[BaseFormSetType[ProductForm]]
else:
    ProductFormSetType = type(_ProductFormSet)

ProductFormSet = _ProductFormSet


class ReceiptForm(ModelForm[Receipt]):
    seller = ModelChoiceField(
        queryset=Seller.objects.all(),
        label=_('Имя продавца'),
        help_text=_(
            'Выберите продавца. Если он ещё не создан, нажмите кнопку ниже.',
        ),
    )
    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт списания'),
        help_text=_(
            'Выберите счёт списания. '
            'Если он ещё не создан, нажмите кнопку ниже.',
        ),
    )
    receipt_date = DateTimeField(
        label=_('Дата и время покупки'),
        help_text=_('Указывается дата и время покупки, указанные в чеке.'),
        input_formats=list(constants.HTML5_DATETIME_LOCAL_INPUT_FORMATS),
        widget=DateTimeInput(
            format=constants.HTML5_DATETIME_LOCAL_INPUT_FORMAT,
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
        help_text=_(
            'Высчитывается автоматически на основании итоговых сумм продуктов',
        ),
        widget=NumberInput(
            attrs={'class': 'total-sum', 'readonly': True},
        ),
    )

    class Meta:
        model = Receipt
        fields: ClassVar[list[str]] = [
            'seller',
            'account',
            'receipt_date',
            'number_receipt',
            'operation_type',
            'nds10',
            'nds20',
            'total_sum',
        ]

    products: Any = _ProductFormSet()


def validate_image_jpg_png(value: UploadedFile) -> None:
    if value.name is None:
        raise ValidationError(_('Имя файла не указано'))
    ext = Path(value.name).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png'):
        raise ValidationError(
            _('Разрешены только файлы форматов: JPG, JPEG или PNG'),
        )


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
                'data-max-size': str(constants.MAX_FILE_SIZE_BYTES),
            },
        ),
        validators=[validate_image_jpg_png],
    )

    def __init__(self, user: User, *args: Any, **kwargs: Any) -> None:
        kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(user=user)  # type: ignore[attr-defined]
        if self.fields['account'].queryset.exists():  # type: ignore[attr-defined]
            self.fields['account'].initial = self.fields[
                'account'
            ].queryset.first()  # type: ignore[attr-defined]

    def clean_file(self) -> Any:
        file = self.cleaned_data.get('file')
        if file and file.size > constants.MAX_FILE_SIZE_BYTES:
            raise ValidationError(
                _(
                    f'Размер файла не должен превышать '
                    f'{constants.MAX_FILE_SIZE_MB}MB',
                ),
            )
        return file


class PendingReceiptReviewForm(Form):
    """Form for reviewing and editing pending receipt data."""

    receipt_date = DateTimeField(
        label=_('Дата и время чека'),
        widget=DateTimeInput(
            attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            },
            format='%Y-%m-%dT%H:%M',
        ),
        required=True,
    )
    name_seller = CharField(
        label=_('Название продавца'),
        max_length=255,
        widget=TextInput(attrs={'class': 'form-control'}),
        required=True,
    )
    retail_place = CharField(
        label=_('Торговая точка'),
        max_length=1000,
        widget=TextInput(attrs={'class': 'form-control'}),
        required=False,
    )
    retail_place_address = CharField(
        label=_('Адрес торговой точки'),
        max_length=1000,
        widget=TextInput(attrs={'class': 'form-control'}),
        required=False,
    )
    number_receipt = IntegerField(
        label=_('Номер чека'),
        widget=NumberInput(attrs={'class': 'form-control'}),
        required=False,
    )
    total_sum = DecimalField(
        label=_('Общая сумма'),
        max_digits=10,
        decimal_places=2,
        widget=NumberInput(
            attrs={
                'class': 'form-control total-sum',
                'step': '0.01',
                'readonly': True,
            },
        ),
        required=True,
    )
    nds10 = DecimalField(
        label=_('НДС 10%'),
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
        widget=NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        required=False,
    )
    nds20 = DecimalField(
        label=_('НДС 20%'),
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
        widget=NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        required=False,
    )
    operation_type = ChoiceField(
        label=_('Тип операции'),
        choices=OPERATION_TYPES,
        widget=Select(attrs={'class': 'form-control'}),
        required=False,
    )

    def __init__(
        self, receipt_data: dict[str, Any], *args: Any, **kwargs: Any
    ) -> None:
        """Initialize form with receipt data.

        Args:
            receipt_data: Dictionary with receipt data.
            *args: Positional arguments.
            **kwargs: Keyword arguments.
        """
        super().__init__(*args, **kwargs)
        if receipt_data:
            receipt_date_str = receipt_data.get('receipt_date', '')
            if receipt_date_str:
                try:
                    day, month, year = receipt_date_str.split(' ')[0].split('.')
                    hour, minute = receipt_date_str.split(' ')[1].split(':')
                    receipt_date = datetime(
                        int(year),
                        int(month),
                        int(day),
                        int(hour),
                        int(minute),
                        tzinfo=timezone.get_current_timezone(),
                    )
                    self.fields['receipt_date'].initial = receipt_date
                except (ValueError, IndexError):
                    self.fields['receipt_date'].initial = receipt_date_str

            self.fields['name_seller'].initial = receipt_data.get('name_seller')
            self.fields['retail_place'].initial = receipt_data.get(
                'retail_place'
            )
            self.fields['retail_place_address'].initial = receipt_data.get(
                'retail_place_address',
            )
            self.fields['number_receipt'].initial = receipt_data.get(
                'number_receipt',
            )
            self.fields['total_sum'].initial = receipt_data.get('total_sum')
            self.fields['nds10'].initial = receipt_data.get('nds10')
            self.fields['nds20'].initial = receipt_data.get('nds20')
            self.fields['operation_type'].initial = receipt_data.get(
                'operation_type',
                0,
            )


class PendingReceiptProductForm(Form):
    """Form for editing a single product in pending receipt."""

    product_name = CharField(
        label=_('Название товара'),
        max_length=1000,
        widget=TextInput(attrs={'class': 'form-control'}),
        required=True,
    )
    category = CharField(
        label=_('Категория'),
        max_length=constants.TWO_HUNDRED_FIFTY,
        widget=TextInput(attrs={'class': 'form-control'}),
        required=False,
    )
    price = DecimalField(
        label=_('Цена за единицу'),
        max_digits=10,
        decimal_places=2,
        widget=NumberInput(
            attrs={'class': 'form-control price', 'step': '0.01'},
        ),
        required=True,
    )
    quantity = DecimalField(
        label=_('Количество'),
        max_digits=10,
        decimal_places=2,
        widget=NumberInput(
            attrs={'class': 'form-control quantity', 'step': '0.01'},
        ),
        required=True,
    )
    amount = DecimalField(
        label=_('Сумма'),
        max_digits=10,
        decimal_places=2,
        widget=NumberInput(
            attrs={
                'class': 'form-control amount',
                'step': '0.01',
                'readonly': True,
            },
        ),
        required=True,
    )
    nds_type = IntegerField(
        label=_('Тип НДС'),
        widget=NumberInput(attrs={'class': 'form-control'}),
        required=False,
    )
    nds_sum = DecimalField(
        label=_('Сумма НДС'),
        max_digits=10,
        decimal_places=2,
        widget=NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        required=False,
    )


PendingReceiptProductFormSet = formset_factory(
    PendingReceiptProductForm,
    extra=0,
    can_delete=True,
)
