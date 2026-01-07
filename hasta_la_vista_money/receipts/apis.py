"""DRF API views for receipts app.

This module provides REST API endpoints for managing receipts,
including creation, listing, deletion, and autocomplete functionality.
"""

import decimal
import json
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
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
from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.api.pagination import StandardResultsSetPagination
from hasta_la_vista_money.api.serializers import GroupQuerySerializer
from hasta_la_vista_money.receipts.mappers.receipt_api_mapper import (
    ReceiptAPIDataMapper,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.serializers import (
    ImageDataSerializer,
    ReceiptSerializer,
    SellerSerializer,
)
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
    """API view for listing and creating receipts.

    Provides endpoints for:
    - GET: List all receipts belonging to the authenticated user
    - POST: Create a new receipt
    """

    schema = AutoSchema()
    serializer_class = ReceiptSerializer
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get_queryset(self) -> QuerySet[Receipt, Receipt]:
        """Return queryset filtered by the current user.

        Returns:
            QuerySet[Receipt, Receipt]: QuerySet of receipts belonging to
                the authenticated user, ordered by receipt_date descending.
        """
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
    """API view for retrieving seller details.

    Provides an endpoint to get detailed information about a seller by ID.
    """

    schema = AutoSchema()
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    lookup_field = 'id'

    def get_queryset(self) -> QuerySet[Seller, Seller]:
        """Return queryset filtered by the current user.

        Returns:
            QuerySet[Seller, Seller]: QuerySet of sellers belonging to
                the authenticated user, ordered by ID descending.
        """
        if getattr(self, 'swagger_fake_view', False):
            return Seller.objects.none()
        user = cast('User', self.request.user)
        return (
            Seller.objects.filter(
                user__id=user.pk,
            )
            .select_related('user')
            .order_by('-id')
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
    """API view for processing receipt image data URL.

    Provides an endpoint to receive receipt image in data URL format
    for processing.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Process receipt image data URL.

        Args:
            request: HTTP request with data_url in request body.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with message and data_url on success,
                or error details on validation failure.
        """
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
    """API view for creating sellers.

    Provides an endpoint to create a new seller for the current user.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a new seller.

        Args:
            request: HTTP request with seller data in request body.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with created seller data on success,
                or validation errors on failure.
        """
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
    """API view for creating receipts.

    Provides an endpoint to create a new receipt with products and seller.
    Includes validation and data mapping logic.
    """

    schema = AutoSchema()
    queryset = Receipt.objects.none()
    serializer_class = ReceiptSerializer
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize view with validator and mapper.

        Args:
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)
        self.validator: ReceiptAPIValidator | None = None
        self.mapper: ReceiptAPIDataMapper | None = None

    def _get_validator(self) -> ReceiptAPIValidator:
        """Get or create validator instance.

        Returns:
            ReceiptAPIValidator: Validator instance for receipt data.
        """
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
        """Get or create mapper instance.

        Returns:
            ReceiptAPIDataMapper: Mapper instance for receipt data.
        """
        if self.mapper is None:
            self.mapper = ReceiptAPIDataMapper()
        return self.mapper

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a new receipt.

        Args:
            request: HTTP request with receipt data in JSON format.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with created receipt data on success,
                or error message on failure.
        """
        return self._process_request(request)

    def _process_request(self, request: Request) -> Response:
        """Process incoming request.

        Args:
            request: HTTP request object.

        Returns:
            Response: JSON response with receipt data or error message.
        """
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
        except DjangoValidationError as error:
            error_message = str(error)
            if hasattr(error, 'message_dict'):
                messages = []
                for errors in error.message_dict.values():
                    if isinstance(errors, list):
                        messages.extend(errors)
                    else:
                        messages.append(str(errors))
                error_message = '; '.join(messages)
            elif hasattr(error, 'messages') and error.messages:
                if isinstance(error.messages, list):
                    error_message = '; '.join(
                        str(msg) for msg in error.messages
                    )
                else:
                    error_message = '; '.join(error.messages)
            elif isinstance(error, DjangoValidationError):
                error_message = str(error)
            return self._error_response(error_message)
        except (ValueError, TypeError, decimal.InvalidOperation) as error:
            return self._error_response(str(error))

    def _handle_receipt_creation(
        self,
        request_data: dict[str, Any],
    ) -> Response:
        """Handle receipt creation using validator and mapper.

        Args:
            request_data: Dictionary with receipt data.

        Returns:
            Response: JSON response with created receipt data.

        Raises:
            ValueError: When validation fails or receipt already exists.
            TypeError: When data type conversion fails.
            decimal.InvalidOperation: When decimal operation fails.
        """
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
        products_data = request_data.get('product', [])

        request_with_container = cast('RequestWithContainer', self.request)
        receipt_creator_service = (
            request_with_container.container.receipts.receipt_creator_service()
        )

        # Check if seller is provided as ID or as object
        seller_in_request = request_data.get('seller')
        seller_id = None
        seller_data = None

        if isinstance(seller_in_request, int):
            # Seller is provided as ID - use it directly
            seller_id = seller_in_request
        else:
            # Seller is provided as object - map it
            seller_data = mapper.map_request_to_seller_data(request_data)

        receipt = receipt_creator_service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=receipt_data,
            seller_id=seller_id,
            seller_data=seller_data,
            products_data=products_data,
        )
        return Response(
            ReceiptSerializer(receipt).data,
            status=status.HTTP_201_CREATED,
        )

    def _error_response(self, message: str) -> Response:
        """Create error response.

        Args:
            message: Error message.

        Returns:
            Response: JSON response with error message and 400 status.
        """
        return Response(
            {'detail': message},
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
    """API view for retrieving receipts by group.

    Provides an endpoint to get a list of receipts filtered by user group.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)
    pagination_class = StandardResultsSetPagination

    def get(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Get receipts by group.

        Args:
            request: HTTP request with group_id query parameter.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: Paginated list of receipts in JSON format with
                user groups information.
        """
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
                    users_in_group,
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
            .order_by('-receipt_date')
        )

        paginator = self.pagination_class()
        paginated_receipts: QuerySet[Receipt, Receipt] | None = (
            paginator.paginate_queryset(receipts, request)  # type: ignore[arg-type]
        )

        if paginated_receipts is None:
            receipt_serializer = ReceiptSerializer(receipts, many=True)
            return Response(
                {
                    'receipts': receipt_serializer.data,
                    'user_groups': user_groups,
                },
                status=status.HTTP_200_OK,
            )

        receipt_serializer = ReceiptSerializer(paginated_receipts, many=True)
        paginated_response = paginator.get_paginated_response(
            receipt_serializer.data,
        )

        paginated_data = paginated_response.data
        if isinstance(paginated_data, dict):
            paginated_data['user_groups'] = user_groups

        return Response(paginated_data, status=status.HTTP_200_OK)


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
    """API view for deleting receipts.

    Provides an endpoint to delete a receipt by its ID.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def delete(
        self,
        request: Request,
        pk: int,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Delete receipt by ID.

        Args:
            request: HTTP request object.
            pk: Receipt ID to delete.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: Empty response with 204 status on success.

        Raises:
            NotFound: When receipt is not found.
            PermissionDenied: When user doesn't have permission to delete.
        """
        try:
            receipt = (
                Receipt.objects.select_related('user', 'seller', 'account')
                .prefetch_related('product')
                .get(id=pk)
            )
        except Receipt.DoesNotExist as e:
            raise NotFound('Receipt not found') from e

        user = cast('User', request.user)
        if receipt.user != user:
            raise PermissionDenied(
                'You do not have permission to delete this receipt',
            )

        with transaction.atomic():
            request_with_container = cast('RequestWithContainer', request)
            container = request_with_container.container
            account_service = container.finance_account.account_service()

            account_service.refund_to_account(
                receipt.account,
                receipt.total_sum,
            )

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
    """API view for seller autocomplete.

    Provides an endpoint to search sellers by name for autocomplete.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
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
    """API view for product autocomplete.

    Provides an endpoint to search products by name for autocomplete.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get product autocomplete suggestions.

        Args:
            request: HTTP request with optional 'q' query parameter.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response: JSON response with list of product names matching
                the search query.
        """
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
