import decimal
import json
from typing import TYPE_CHECKING, Any, cast

from django.db.models import QuerySet
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.mappers.receipt_api_mapper import (
    ReceiptAPIDataMapper,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.serializers import (
    ImageDataSerializer,
    ReceiptSerializer,
    SellerSerializer,
)
from hasta_la_vista_money.api.pagination import StandardResultsSetPagination
from hasta_la_vista_money.api.serializers import GroupQuerySerializer
from hasta_la_vista_money.receipts.validators.receipt_api_validator import (
    ReceiptAPIValidator,
)
from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['receipts'],
    summary='Список чеков',
    description='Получить список всех чеков текущего пользователя',
)
class ReceiptListAPIView(ListCreateAPIView[Receipt]):
    schema = AutoSchema()
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get_queryset(self) -> QuerySet[Receipt, Receipt]:
        if getattr(self, 'swagger_fake_view', False):
            return Receipt.objects.none()
        user = cast('User', self.request.user)
        return (
            Receipt.objects.filter(user=user)
            .select_related('seller', 'account', 'user')
            .prefetch_related('product')
            .order_by('-receipt_date')
        )


@extend_schema(
    tags=['receipts'],
    summary='Детали продавца',
    description='Получить детальную информацию о продавце по ID',
)
class SellerDetailAPIView(RetrieveAPIView[Seller]):
    schema = AutoSchema()
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    lookup_field = 'id'

    def get_queryset(self) -> QuerySet[Seller, Seller]:
        if getattr(self, 'swagger_fake_view', False):
            return Seller.objects.none()
        user = cast('User', self.request.user)
        return Seller.objects.filter(
            user__id=user.pk,
        ).select_related('user').order_by('-id')


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
class ReceiptCreateAPIView(ListCreateAPIView[Receipt]):
    schema = AutoSchema()
    queryset = Receipt.objects.none()
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize view with validator and mapper."""
        super().__init__(*args, **kwargs)
        self.validator: ReceiptAPIValidator | None = None
        self.mapper: ReceiptAPIDataMapper | None = None

    def _get_validator(self) -> ReceiptAPIValidator:
        """Get or create validator instance."""
        if self.validator is None:
            request_with_container = cast('RequestWithContainer', self.request)
            receipt_repository = (
                request_with_container.container.receipts.receipt_repository()
            )
            self.validator = ReceiptAPIValidator(
                receipt_repository=receipt_repository,
            )
        return self.validator

    def _get_mapper(self) -> ReceiptAPIDataMapper:
        """Get or create mapper instance."""
        if self.mapper is None:
            self.mapper = ReceiptAPIDataMapper()
        return self.mapper

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._process_request(request)

    def _process_request(self, request: Request) -> Response:
        """Process incoming request."""
        try:
            request_data = json.loads(request.body)
        except json.JSONDecodeError:
            return self._error_response('Invalid JSON data')

        validator = self._get_validator()
        validation_result = validator.validate_json_data(request_data)
        if not validation_result.is_valid:
            return self._error_response(
                validation_result.error or 'Validation failed',
            )

        try:
            return self._handle_receipt_creation(request_data)
        except (ValueError, TypeError, decimal.InvalidOperation) as error:
            return self._error_response(str(error))

    def _handle_receipt_creation(
        self,
        request_data: dict[str, Any],
    ) -> Response:
        """Handle receipt creation using validator and mapper."""
        validator = self._get_validator()
        mapper = self._get_mapper()

        # Validate user and account
        user_id = request_data.get('user')
        account_id = request_data.get('finance_account')
        validation_result = validator.validate_user_and_account(
            user_id,
            account_id,
        )
        if not validation_result.is_valid:
            return self._error_response(
                validation_result.error or 'User or account validation failed',
            )

        user = cast('User', validation_result.user)
        account = cast('Account', validation_result.account)

        # Check if receipt already exists
        if validator.check_receipt_exists(request_data, user):
            return self._error_response('Такой чек уже был добавлен ранее')

        # Map data and create receipt
        receipt_data = mapper.map_request_to_receipt_data(request_data)
        seller_data = mapper.map_request_to_seller_data(request_data)
        products_data = request_data.get('product', [])

        request_with_container = cast('RequestWithContainer', self.request)
        receipt_creator_service = (
            request_with_container.container.receipts.receipt_creator_service()
        )
        receipt = receipt_creator_service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=receipt_data,
            seller_data=seller_data,
            products_data=products_data,
        )
        return Response(
            ReceiptSerializer(receipt).data,
            status=status.HTTP_201_CREATED,
        )

    def _error_response(self, message: str) -> Response:
        return Response(
            message,
            status=status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(
    tags=['receipts'],
    summary='Получить чеки по группе',
    description='Получить список чеков для указанной группы пользователей',
    parameters=[
        OpenApiParameter(
            name='group_id',
            type=str,
            location=OpenApiParameter.QUERY,
            description='ID группы (по умолчанию "my")',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Список чеков',
            response={
                'type': 'object',
                'properties': {
                    'receipts': {
                        'type': 'array',
                        'items': {'$ref': '#/components/schemas/Receipt'},
                    },
                    'user_groups': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer'},
                                'name': {'type': 'string'},
                            },
                        },
                    },
                },
            },
        ),
    },
)
class ReceiptsByGroupAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view для получения чеков по группе."""

    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Получить чеки по группе."""
        query_serializer = GroupQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        group_id = query_serializer.validated_data.get('group_id', 'my')

        request_with_container = cast('RequestWithContainer', request)
        receipt_repository = (
            request_with_container.container.receipts.receipt_repository()
        )

        if not isinstance(request.user, User):
            receipt_queryset = receipt_repository.filter(pk__in=[])
            user_groups = []
        else:
            user = User.objects.prefetch_related('groups').get(
                pk=request.user.pk,
            )
            account_service = (
                request_with_container.container.core.account_service()
            )
            users_in_group = account_service.get_users_for_group(user, group_id)

            if users_in_group:
                receipt_queryset = receipt_repository.get_by_users(
                    users_in_group
                )
            else:
                receipt_queryset = receipt_repository.filter(pk__in=[])

            user_groups = [
                {'id': group.pk, 'name': group.name}
                for group in user.groups.all()
            ]

        receipts = (
            receipt_queryset.select_related('seller', 'user')
            .prefetch_related('product')
            .order_by('-receipt_date')[: constants.RECENT_RECEIPTS_LIMIT]
        )

        receipt_serializer = ReceiptSerializer(receipts, many=True)

        return Response(
            {
                'receipts': receipt_serializer.data,
                'user_groups': user_groups,
            },
            status=status.HTTP_200_OK,
        )


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
            receipt = (
                Receipt.objects.select_related('user', 'seller', 'account')
                .prefetch_related('product')
                .get(id=pk)
            )
        except Receipt.DoesNotExist:
            raise NotFound('Receipt not found')

        user = cast('User', request.user)
        if receipt.user != user:
            raise PermissionDenied('You do not have permission to delete this receipt')

        receipt.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = request.GET.get('q', '').strip()
        user = cast('User', request.user)
        sellers: QuerySet[Seller, Seller] = Seller.objects.filter(
            user=user,
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
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = request.GET.get('q', '').strip()
        user = cast('User', request.user)
        products: QuerySet[Product, Product] = Product.objects.filter(
            user=user,
        ).only('product_name')
        if query:
            products = products.filter(product_name__icontains=query)
        product_names: QuerySet[Product, str] = products.values_list(
            'product_name',
            flat=True,
        ).distinct()[: constants.RECEIPTS_DISTINCT_LIMIT]
        return Response({'results': list(product_names)})
