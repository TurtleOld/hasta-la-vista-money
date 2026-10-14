"""DRF API views for users app."""

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import (
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
from hasta_la_vista_money.users.services.groups import get_user_groups

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['users'],
    summary='Получить группы пользователя',
    description=(
        'Получить список групп, в которых состоит текущий пользователь'
    ),
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
class UserGroupsAPIView(APIView):
    """API view for getting user groups.

    Returns list of groups that the current user belongs to.
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
        user = cast('User', request.user)
        groups = get_user_groups(user)

        return Response({'groups': groups}, status=status.HTTP_200_OK)


@extend_schema(
    tags=['users'],
    summary='Получить доступные группы',
    description=(
        'Группы системы не перечисляются: всегда возвращается пустой список'
    ),
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
class AvailableGroupsAPIView(APIView):
    """API view for getting available groups for user.

    Groups of other users are never enumerated, so the list is always empty.
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
        groups: list[dict[str, Any]] = []

        return Response({'groups': groups}, status=status.HTTP_200_OK)
