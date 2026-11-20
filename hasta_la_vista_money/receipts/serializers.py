from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import CharField, ModelSerializer, Serializer

from hasta_la_vista_money.receipts.models import Product, Receipt, Seller

if TYPE_CHECKING:

    class _MetaBase(ModelSerializer.Meta):
        """Static-only Meta base matching DRF stubs."""

else:
    from django_stubs_ext.db.models import TypedModelMeta as _MetaBase


class InvalidSellerDataError(ValidationError):
    default_detail = 'Invalid seller data'


class InvalidProductDataError(ValidationError):
    default_detail = 'Invalid product data'


class SellerSerializer(ModelSerializer[Seller]):
    class Meta(_MetaBase):
        model: ClassVar[type[Any]] = Seller
        fields: ClassVar[Sequence[str] | Literal['__all__']] = '__all__'
        read_only_fields: ClassVar[Sequence[str] | None] = ('user',)


class ProductSerializer(ModelSerializer[Product]):
    class Meta(_MetaBase):
        model: ClassVar[type[Any]] = Product
        fields: ClassVar[Sequence[str] | Literal['__all__']] = '__all__'


class ReceiptSerializer(ModelSerializer[Receipt]):
    product = ProductSerializer(many=True)

    class Meta(_MetaBase):
        model: ClassVar[type[Any]] = Receipt
        fields: ClassVar[Sequence[str] | Literal['__all__']] = '__all__'

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Receipt:
        products_data = validated_data.pop('product')
        seller_data = validated_data.pop('seller')
        seller_serializer = SellerSerializer(data=seller_data)
        if not seller_serializer.is_valid():
            raise InvalidSellerDataError
        seller = seller_serializer.save()
        receipt = Receipt.objects.create(seller=seller, **validated_data)
        products = []
        for product_data in products_data:
            product_serializer = ProductSerializer(data=product_data)
            if not product_serializer.is_valid():
                raise InvalidProductDataError
            products.append(product_serializer.save())
        receipt.product.set(products)
        return receipt


class ImageDataSerializer(Serializer[dict[str, Any]]):
    data_url = CharField(required=True)
