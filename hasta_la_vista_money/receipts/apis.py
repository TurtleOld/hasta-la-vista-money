import decimal
import json

from django.db.models import QuerySet
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.serializers import (
    ImageDataSerializer,
    ReceiptSerializer,
    SellerSerializer,
)
from hasta_la_vista_money.users.models import User
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ReceiptListAPIView(ListCreateAPIView):
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Receipt, Receipt]:  # type: ignore[override]
        return (
            Receipt.objects.filter(user=self.request.user)
            .select_related('seller', 'account', 'user')
            .prefetch_related('product')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = ReceiptSerializer(queryset, many=True)
        return Response(serializer.data)


class SellerDetailAPIView(RetrieveAPIView):
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'id'

    def get_queryset(self) -> QuerySet[Seller, Seller]:  # type: ignore[override]
        return Seller.objects.filter(user__id=self.request.user.pk).select_related(
            'user',
        )


class DataUrlAPIView(APIView):
    def post(self, request):
        serializer = ImageDataSerializer(data=request.data)

        if serializer.is_valid():
            validated_data = serializer.validated_data
            if validated_data is None:
                return Response(
                    'Invalid data',
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data_url = validated_data.get('data_url')  # type: ignore[attr-defined]
            if data_url is None:
                return Response(
                    'Data URL is required',
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {'message': 'Data URL received successfully', 'data_url': data_url},
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )


class SellerCreateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        serializer = SellerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReceiptCreateAPIView(ListCreateAPIView):
    def post(self, request, *args, **kwargs):
        request_data = json.loads(request.body)
        user_id = request_data.get('user')
        account_id = request_data.get('finance_account')
        receipt_date = request_data.get('receipt_date')
        total_sum = request_data.get('total_sum')
        number_receipt = request_data.get('number_receipt')
        operation_type = request_data.get('operation_type')
        nds10 = request_data.get('nds10')
        nds20 = request_data.get('nds20')
        seller_data = request_data.get('seller')
        products_data = request_data.get('product')

        if not all(
            [user_id, account_id, receipt_date, total_sum, seller_data, products_data],
        ):
            return Response(
                'Missing required data',
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            check_existing_receipt = Receipt.objects.filter(
                receipt_date=receipt_date,
                total_sum=total_sum,
            ).first()

            if not check_existing_receipt:
                user = User.objects.get(id=user_id)
                seller_data['user'] = user
                account = Account.objects.get(id=account_id)
                account.balance -= decimal.Decimal(total_sum)
                account.save()
                request_data['account'] = account
                seller = Seller.objects.create(**seller_data)
                receipt = Receipt.objects.create(
                    user=user,
                    account=account,
                    receipt_date=receipt_date,
                    seller=seller,
                    total_sum=total_sum,
                    number_receipt=number_receipt,
                    operation_type=operation_type,
                    nds10=nds10,
                    nds20=nds20,
                )

                products_data = []
                for product_data in products_data:
                    product_data.pop('receipt', None)
                    product_data['user'] = user
                    products_data.append(Product(**product_data))

                products = Product.objects.bulk_create(products_data)

                receipt.product.set(products)

                return Response(
                    ReceiptSerializer(receipt).data,
                    status=status.HTTP_201_CREATED,
                )
            return Response(
                'Такой чек уже был добавлен ранее',
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as error:
            return Response(
                str(error),
                status=status.HTTP_400_BAD_REQUEST,
            )


class SellerAutocompleteAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '').strip()
        sellers: QuerySet[Seller, Seller] = Seller.objects.filter(
            user=request.user,
        ).only('name_seller')
        if query:
            sellers = sellers.filter(name_seller__icontains=query)
        seller_names: QuerySet[Seller, str] = sellers.values_list(
            'name_seller',
            flat=True,
        ).distinct()[:10]
        return Response({'results': list(seller_names)})


class ProductAutocompleteAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '').strip()
        products: QuerySet[Product, Product] = Product.objects.filter(
            user=request.user,
        ).only('product_name')
        if query:
            products = products.filter(product_name__icontains=query)
        product_names: QuerySet[Product, str] = products.values_list(
            'product_name',
            flat=True,
        ).distinct()[:10]
        return Response({'results': list(product_names)})
