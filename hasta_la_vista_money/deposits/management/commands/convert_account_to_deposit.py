from argparse import ArgumentParser
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.commands import (
    ConvertAccountToDepositCommand,
)
from hasta_la_vista_money.deposits.models import DepositTerm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.services.dashboard_kpis import (
    DashboardKpiDict,
    get_dashboard_month_kpis,
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=UTC).date()


def _format_kpis(kpis: DashboardKpiDict) -> list[str]:
    return [
        f'income: {kpis["income"]}',
        f'expenses: {kpis["expenses"]}',
        f'net_result: {kpis["net_result"]}',
        f'savings_rate: {kpis["savings_rate"]}',
    ]


class Command(BaseCommand):
    help = (
        'Convert an existing production account into a term deposit, '
        'preserving its PK, balance, currency, owner, and timestamps.'
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            '--account-id',
            type=int,
            required=True,
            help='PK of the existing account to convert.',
        )
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Name of the deposit agreement.',
        )
        parser.add_argument(
            '--bank',
            type=str,
            required=True,
            help='Bank code for the deposit agreement.',
        )
        parser.add_argument(
            '--opened-on',
            type=_parse_date,
            required=True,
            help='Deposit term opening date (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--matures-on',
            type=_parse_date,
            required=True,
            help='Deposit term maturity date (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--annual-rate',
            type=Decimal,
            required=True,
            help='Annual interest rate for the current term.',
        )
        parser.add_argument(
            '--converted-on',
            type=_parse_date,
            required=True,
            help='Date of the neutral opening-position event (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=True,
            help='Show what would change without writing (default).',
        )
        parser.add_argument(
            '--no-dry-run',
            action='store_false',
            dest='dry_run',
            help='Actually perform the conversion.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        account_repository = (
            ApplicationContainer().finance_account.account_repository()
        )
        try:
            account = account_repository.get_by_id(options['account_id'])
        except Account.DoesNotExist as error:
            raise CommandError('Счёт не найден.') from error

        kpis_before = get_dashboard_month_kpis(account.user)
        self.stdout.write('=== Счёт до преобразования ===')
        self.stdout.write(f'ID: {account.pk}')
        self.stdout.write(f'Владелец: {account.user}')
        self.stdout.write(f'Текущий тип: {account.type_account}')
        self.stdout.write(f'Остаток: {account.balance}')
        self.stdout.write(f'Валюта: {account.currency}')
        self.stdout.write(
            f'Создаваемый срок: {options["opened_on"]} -> '
            f'{options["matures_on"]}, ставка {options["annual_rate"]}%',
        )
        self.stdout.write(
            f'Дата начальной позиции: {options["converted_on"]}',
        )
        self.stdout.write('--- Контрольные KPI до ---')
        for line in _format_kpis(kpis_before):
            self.stdout.write(line)

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING('Dry-run: изменения не записаны.'),
            )
            return

        service = ApplicationContainer().deposits.deposit_service()
        try:
            service.convert_account_to_deposit(
                ConvertAccountToDepositCommand(
                    user=account.user,
                    account_id=account.pk,
                    name=options['name'],
                    bank=options['bank'],
                    opened_on=options['opened_on'],
                    matures_on=options['matures_on'],
                    annual_rate=options['annual_rate'],
                    converted_on=options['converted_on'],
                    rate_kind=DepositTerm.RateKind.FIXED,
                ),
            )
        except ValidationError as error:
            raise CommandError(str(error)) from error

        account.refresh_from_db()
        kpis_after = get_dashboard_month_kpis(account.user)
        self.stdout.write(
            self.style.SUCCESS('=== Счёт после преобразования ==='),
        )
        self.stdout.write(f'Новый тип: {account.type_account}')
        self.stdout.write(f'Остаток: {account.balance}')
        self.stdout.write('--- Контрольные KPI после ---')
        for line in _format_kpis(kpis_after):
            self.stdout.write(line)
