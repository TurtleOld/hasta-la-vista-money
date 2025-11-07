import decimal
import json
from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.serializers import (
    ImageDataSerializer,
    ReceiptSerializer,
    SellerSerializer,
)
from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['receipts'],
    summary='Список чеков',
    description='Получить список всех чеков текущего пользователя',
)
class ReceiptListAPIView(ListCreateAPIView):
    schema = AutoSchema()
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get_queryset(self) -> QuerySet[Receipt, Receipt]:
        if getattr(self, 'swagger_fake_view', False):
            return Receipt.objects.none()
        return (
            Receipt.objects.filter(user=self.request.user)
            .select_related('seller', 'account', 'user')
            .prefetch_related('product')
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.get_queryset()
        serializer = ReceiptSerializer(queryset, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=['receipts'],
    summary='Детали продавца',
    description='Получить детальную информацию о продавце по ID',
)
class SellerDetailAPIView(RetrieveAPIView):
    schema = AutoSchema()
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    lookup_field = 'id'

    def get_queryset(self) -> QuerySet[Seller, Seller]:
        if getattr(self, 'swagger_fake_view', False):
            return Seller.objects.none()
        return Seller.objects.filter(
            user__id=self.request.user.pk,
        ).select_related(
            'user',
        )


@extend_schema(
    tags=['receipts'],
    summary='Обработка изображения чека',
    description='Отправить изображение чека в формате data URL для обработки',
    request=ImageDataSerializer,
    responses={
        200: OpenApiResponse(
            description='Изображение успешно получено',
            response={
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'data_url': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(description='Неверные данные'),
    },
)
class DataUrlAPIView(APIView):
    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ImageDataSerializer(data=request.data)

        if serializer.is_valid():
            validated_data = serializer.validated_data
            if validated_data is None:
                return Response(
                    'Invalid data',
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data_url = validated_data.get('data_url')
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


@extend_schema(
    tags=['receipts'],
    summary='Создать продавца',
    description='Создать нового продавца для текущего пользователя',
    request=SellerSerializer,
    responses={
        201: SellerSerializer,
        400: OpenApiResponse(description='Неверные данные'),
    },
)
class SellerCreateAPIView(APIView):
    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SellerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=['receipts'],
    summary='Создать чек',
    description='Создать новый чек с товарами и продавцом',
    request=ReceiptSerializer,
    responses={
        201: ReceiptSerializer,
        400: OpenApiResponse(description='Неверные данные'),
    },
)
class ReceiptCreateAPIView(ListCreateAPIView):
    schema = AutoSchema()
    queryset = Receipt.objects.none()
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._process_request(request)

    def _process_request(self, request: Request) -> Response:
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
        if isinstance(user, Response) or user is None:
            return (
                user
                if isinstance(user, Response)
                else self._error_response('User not found')
            )
        if isinstance(account, Response) or account is None:
            return (
                account
                if isinstance(account, Response)
                else self._error_response('Account not found')
            )

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
            ).first(),
        )

    def _get_user_and_account(
        self,
        request_data: dict,
    ) -> tuple[User | Response | None, Account | Response | None]:
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
        seller_data: dict = request_data.get('seller') or {}
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

        products = request_data.get('product')
        if products:
            self._create_products(products, user, receipt)
        return receipt

    def _create_products(
        self,
        products_data: list,
        user: User,
        receipt: Receipt,
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


@extend_schema(
    tags=['receipts'],
    summary='Удалить чек',
    description='Удалить чек по его ID',
    responses={
        204: OpenApiResponse(description='Чек успешно удален'),
        404: OpenApiResponse(description='Чек не найден'),
    },
)
class ReceiptDeleteAPIView(APIView):
    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def delete(
        self,
        request: Request,
        pk: int,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        try:
            receipt = Receipt.objects.get(id=pk)
            receipt.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Receipt.DoesNotExist:
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={'error': 'Receipt not found'},
            )


@extend_schema(
    tags=['receipts'],
    summary='Автодополнение продавцов',
    description='Поиск продавцов по имени для автодополнения',
    parameters=[
        OpenApiParameter(
            name='q',
            type=str,
            location=OpenApiParameter.QUERY,
            description='Поисковый запрос для фильтрации продавцов',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Список найденных продавцов',
            response={
                'type': 'object',
                'properties': {
                    'results': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                },
            },
        ),
    },
)
class SellerAutocompleteAPIView(APIView):
    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = request.GET.get('q', '').strip()
        sellers: QuerySet[Seller, Seller] = Seller.objects.filter(
            user=request.user,
        ).only('name_seller')
        if query:
            sellers = sellers.filter(name_seller__icontains=query)
        seller_names: QuerySet[Seller, str] = sellers.values_list(
            'name_seller',
            flat=True,
        ).distinct()[: constants.RECEIPTS_DISTINCT_LIMIT]
        return Response({'results': list(seller_names)})


@extend_schema(
    tags=['receipts'],
    summary='Автодополнение товаров',
    description='Поиск товаров по названию для автодополнения',
    parameters=[
        OpenApiParameter(
            name='q',
            type=str,
            location=OpenApiParameter.QUERY,
            description='Поисковый запрос для фильтрации товаров',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Список найденных товаров',
            response={
                'type': 'object',
                'properties': {
                    'results': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                },
            },
        ),
    },
)
class ProductAutocompleteAPIView(APIView):
    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = request.GET.get('q', '').strip()
        products: QuerySet[Product, Product] = Product.objects.filter(
            user=request.user,
        ).only('product_name')
        if query:
            products = products.filter(product_name__icontains=query)
        product_names: QuerySet[Product, str] = products.values_list(
            'product_name',
            flat=True,
        ).distinct()[: constants.RECEIPTS_DISTINCT_LIMIT]
        return Response({'results': list(product_names)})
