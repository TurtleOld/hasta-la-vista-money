"""DRF API views for users app."""

from typing import Any, cast

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.core.mixins import (
    FormErrorHandlingMixin,
    UserAuthMixin,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.groups import (
    get_groups_not_for_user,
    get_user_groups,
)


@extend_schema(
    tags=['users'],
    summary='Получить группы пользователя',
    description=(
        'Получить список всех групп, в которых состоит указанный пользователь'
    ),
    parameters=[
        OpenApiParameter(
            name='user_id',
            type=int,
            location=OpenApiParameter.QUERY,
            description='ID пользователя',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Список групп пользователя',
            response={
                'type': 'object',
                'properties': {
                    'groups': {
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
class UserGroupsAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for getting user groups.

    Returns list of groups that the specified user belongs to.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get user groups.

        Args:
            request: HTTP request object.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response with user groups list.
        """
        user_id = request.query_params.get('user_id')

        if user_id:
            try:
                user = User.objects.get(pk=int(user_id))
                groups = get_user_groups(user)
            except (User.DoesNotExist, ValueError):
                groups = []
        else:
            # Если user_id не указан, возвращаем группы текущего пользователя
            user = cast('User', request.user)
            groups = get_user_groups(user)

        return Response({'groups': groups}, status=status.HTTP_200_OK)


@extend_schema(
    tags=['users'],
    summary='Получить доступные группы',
    description=(
        'Получить список групп, в которых не состоит указанный пользователь'
    ),
    parameters=[
        OpenApiParameter(
            name='user_id',
            type=int,
            location=OpenApiParameter.QUERY,
            description='ID пользователя',
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Список доступных групп',
            response={
                'type': 'object',
                'properties': {
                    'groups': {
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
class AvailableGroupsAPIView(APIView, UserAuthMixin, FormErrorHandlingMixin):
    """API view for getting available groups for user.

    Returns list of groups that the specified user does not belong to.
    """

    schema = AutoSchema()
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get available groups for user.

        Args:
            request: HTTP request object.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Response with available groups list.
        """
        user_id = request.query_params.get('user_id')

        if user_id:
            try:
                user = User.objects.get(pk=int(user_id))
                groups = get_groups_not_for_user(user)
            except (User.DoesNotExist, ValueError):
                groups = []
        else:
            user = cast('User', request.user)
            groups = get_groups_not_for_user(user)

        return Response({'groups': groups}, status=status.HTTP_200_OK)
