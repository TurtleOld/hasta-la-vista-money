from decimal import Decimal

import factory

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.factories import UserFactory


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    user = factory.SubFactory(UserFactory)
    name_account = factory.Sequence(lambda n: f'Account {n}')
    balance = Decimal('1000.00')
    currency = 'RUB'


class TransferMoneyLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TransferMoneyLog

    user = factory.SubFactory(UserFactory)
    from_account = factory.SubFactory(AccountFactory)
    to_account = factory.SubFactory(AccountFactory)
    amount = Decimal('100.00')
    exchange_date = '2024-01-01'
    notes = factory.Faker('sentence')
