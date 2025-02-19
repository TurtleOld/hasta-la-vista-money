from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.serializers import AccountSerializer
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class AccountListCreateAPIView(ListCreateAPIView):
    serializer_class = AccountSerializer
    permission_classes = (IsAuthenticated,)

    @property
    def queryset(self):
        return Account.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = AccountSerializer(queryset, many=True)
        return Response(serializer.data)
