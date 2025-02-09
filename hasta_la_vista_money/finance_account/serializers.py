from hasta_la_vista_money.finance_account.models import Account
from rest_framework import serializers


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'name_account', 'balance', 'currency']
