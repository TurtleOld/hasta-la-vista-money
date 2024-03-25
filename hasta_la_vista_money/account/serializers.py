from hasta_la_vista_money.account.models import Account
from rest_framework import serializers


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['name_account', 'balance', 'currency']