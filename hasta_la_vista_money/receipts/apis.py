import decimal
import json
from datetime import datetime
from typing import ClassVar

from django.db.models import QuerySet
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.serializers import (
    ImageDataSerializer,
    ReceiptSerializer,
    SellerSerializer,
)
from hasta_la_vista_money.users.models import User


class ReceiptListAPIView(ListCreateAPIView):
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]

    def get_queryset(self) -> QuerySet[Receipt, Receipt]:  # type: ignore[override]
        return (
            Receipt.objects.filter(user=self.request.user)
            .select_related('seller', 'account', 'user')
            .prefetch_related('product')
        )

    def list(self, request) -> Response:
        queryset = self.get_queryset()
        serializer = ReceiptSerializer(queryset, many=True)
        return Response(serializer.data)


class SellerDetailAPIView(RetrieveAPIView):
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]
    lookup_field = 'id'

    def get_queryset(self) -> QuerySet[Seller, Seller]:  # type: ignore[override]
        return Seller.objects.filter(
            user__id=self.request.user.pk,
        ).select_related(
            'user',
        )


class DataUrlAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]

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
                {
                    'message': 'Data URL received successfully',
                    'data_url': data_url,
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class SellerCreateAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]

    def post(self, request):
        serializer = SellerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReceiptCreateAPIView(ListCreateAPIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]

    def post(self, request):
        return self._process_request(request)

    def _process_request(self, request) -> Response:
        try:
            request_data = json.loads(request.body)
        except json.JSONDecodeError:
            return self._error_response('Invalid JSON data')

        validation_error = self._validate_request_data(request_data)
        if validation_error:
            return validation_error

        try:
            return self._handle_receipt_creation(request_data)
        except (ValueError, TypeError, decimal.InvalidOperation) as error:
            return self._error_response(str(error))

    def _handle_receipt_creation(self, request_data: dict) -> Response:
        if self._check_existing_receipt(request_data):
            return self._error_response('Такой чек уже был добавлен ранее')

        user, account = self._get_user_and_account(request_data)
        if isinstance(user, Response):
            return user
        if isinstance(account, Response):
            return account

        receipt = self._create_receipt(request_data, user, account)
        return Response(
            ReceiptSerializer(receipt).data,
            status=status.HTTP_201_CREATED,
        )

    def _error_response(self, message: str) -> Response:
        return Response(
            message,
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _validate_request_data(self, request_data: dict) -> Response | None:
        required_fields = [
            'user',
            'finance_account',
            'receipt_date',
            'total_sum',
            'seller',
            'product',
        ]
        if not all(request_data.get(field) for field in required_fields):
            return self._error_response('Missing required data')
        return None

    def _check_existing_receipt(self, request_data: dict) -> bool:
        return bool(
            Receipt.objects.filter(
                receipt_date=request_data.get('receipt_date'),
                total_sum=request_data.get('total_sum'),
            ).first()
        )

    def _get_user_and_account(
        self,
        request_data: dict,
    ) -> tuple[User | Response, Account | Response]:
        user_id = request_data.get('user')
        account_id = request_data.get('finance_account')

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return (
                self._error_response(f'User with id {user_id} does not exist'),
                None,
            )

        try:
            account = Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return (
                None,
                self._error_response(
                    f'Account with id {account_id} does not exist '
                    f'or does not belong to user {user_id}',
                ),
            )

        return user, account

    def _create_receipt(
        self,
        request_data: dict,
        user: User,
        account: Account,
    ) -> Receipt:
        seller_data = request_data.get('seller')
        seller_data['user'] = user

        account.balance -= decimal.Decimal(str(request_data.get('total_sum')))
        account.save()

        seller = Seller.objects.create(**seller_data)

        receipt_date = request_data.get('receipt_date')
        if isinstance(receipt_date, str):
            receipt_date = datetime.fromisoformat(receipt_date)

        receipt = Receipt.objects.create(
            user=user,
            account=account,
            receipt_date=receipt_date,
            seller=seller,
            total_sum=decimal.Decimal(str(request_data.get('total_sum'))),
            number_receipt=request_data.get('number_receipt'),
            operation_type=request_data.get('operation_type'),
            nds10=decimal.Decimal(str(request_data.get('nds10')))
            if request_data.get('nds10')
            else None,
            nds20=decimal.Decimal(str(request_data.get('nds20')))
            if request_data.get('nds20')
            else None,
        )

        self._create_products(request_data.get('product'), user, receipt)
        return receipt

    def _create_products(
        self, products_data: list, user: User, receipt: Receipt
    ) -> None:
        products_objects = []
        for product_data in products_data:
            product_data_copy = product_data.copy()
            product_data_copy.pop('receipt', None)
            product_data_copy['user'] = user

            self._process_product_data(product_data_copy)
            products_objects.append(Product(**product_data_copy))

        products = Product.objects.bulk_create(products_objects)
        receipt.product.set(products)

    def _process_product_data(self, product_data: dict) -> None:
        decimal_fields = ['price', 'quantity', 'amount']
        for field in decimal_fields:
            if field in product_data:
                product_data[field] = decimal.Decimal(str(product_data[field]))

        if 'category' in product_data and product_data['category'] is None:
            product_data['category'] = ''


class ReceiptDeleteAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes: ClassVar[list[type[BaseThrottle]]] = [UserRateThrottle]

    def delete(self, pk: int) -> Response:
        try:
            receipt = Receipt.objects.get(id=pk)
            receipt.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Receipt.DoesNotExist:
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={'error': 'Receipt not found'},
            )


class SellerAutocompleteAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
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

    def get(self, request):
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
