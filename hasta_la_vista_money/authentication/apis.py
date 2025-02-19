import json

from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.serializers import UserSerializer
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ListUsersAPIView(ListCreateAPIView):
    authentication_classes = (TokenAuthentication,)
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        user = request.user
        return Response(
            {'id': user.id, 'username': user.username},
            status=status.HTTP_200_OK,
        )


class LoginUserAPIView(APIView):
    def post(self, request):
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')

        if '@' in username:
            user = User.objects.get(email=username)
        else:
            user = User.objects.get(username=username)

        if user is not None and user.check_password(password):
            token, _ = Token.objects.get_or_create(user=user)
            print(token)
            return Response(
                {'token': token.key, 'user': user.username},
                status=status.HTTP_200_OK,
            )
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
