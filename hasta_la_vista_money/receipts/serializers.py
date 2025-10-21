from django_stubs_ext.db.models import TypedModelMeta
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import CharField, ModelSerializer, Serializer

from hasta_la_vista_money.receipts.models import Product, Receipt, Seller


class SellerSerializer(ModelSerializer):
    class Meta(TypedModelMeta):
        model = Seller
        fields = '__all__'
        read_only_fields = ('user',)


class ProductSerializer(ModelSerializer):
    class Meta(TypedModelMeta):
        model = Product
        fields = '__all__'


class ReceiptSerializer(ModelSerializer):
    product = ProductSerializer(many=True)

    class Meta(TypedModelMeta):
        model = Receipt
        fields = '__all__'

    def create(self, validated_data):
        products_data = validated_data.pop('product')
        seller_data = validated_data.pop('seller')
        seller_serializer = SellerSerializer(data=seller_data)
        if not seller_serializer.is_valid():
            raise ValidationError('Invalid seller data')
        seller = seller_serializer.save()
        receipt = Receipt.objects.create(seller=seller, **validated_data)
        for product_data in products_data:
            product_serializer = ProductSerializer(data=product_data)
            if not product_serializer.is_valid():
                raise ValidationError('Invalid product data')
            product = product_serializer.save()
            receipt.product.add(product)
        return receipt


class ImageDataSerializer(Serializer):
    data_url = CharField(required=True)
