from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEPOSIT
from hasta_la_vista_money.deposits.commands import (
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    FundDepositCommand,
    OpenExistingDepositCommand,
)
from hasta_la_vista_money.deposits.models import Deposit, DepositPrincipalEvent
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.services.dashboard_kpis import (
    get_dashboard_month_kpis,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class DepositServiceIntegrationTests(TestCase):
    def test_confirmed_principal_event_cannot_be_changed_or_deleted(
        self,
    ) -> None:
        """Principal events reject save, delete, bulk update, and
        bulk delete."""
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.open_existing_term_deposit(
            OpenExistingDepositCommand(
                user=user,
                name='Неизменяемая история',
                bank='SBERBANK',
                currency='RUB',
                current_balance=Decimal('75000.00'),
                tracking_started_on=date(2026, 7, 15),
                opened_on=date(2026, 6, 1),
                matures_on=date(2026, 12, 1),
                annual_rate=Decimal('14.00'),
            ),
        )
        event = DepositPrincipalEvent.objects.get(deposit=deposit)

        event.amount = Decimal('1.00')
        with self.assertRaisesMessage(
            ValidationError,
            'Подтверждённое событие вклада нельзя изменить.',
        ):
            event.save()
        with self.assertRaisesMessage(
            ValidationError,
            'Подтверждённое событие вклада нельзя удалить.',
        ):
            event.delete()
        with self.assertRaises(ValidationError):
            DepositPrincipalEvent.objects.filter(pk=event.pk).update(
                amount=Decimal('1.00'),
            )
        with self.assertRaises(ValidationError):
            DepositPrincipalEvent.objects.filter(pk=event.pk).delete()

        event.refresh_from_db()
        self.assertEqual(event.amount, Decimal('75000.00'))

    def test_funding_rejects_ineligible_source_accounts_and_amounts(
        self,
    ) -> None:
        """Reject foreign accounts, other currencies, negative amounts, and
        insufficient funds."""
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        valid_source = Account.objects.create(
            user=user,
            name_account='Рубли',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        foreign_source = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        usd_source = Account.objects.create(
            user=user,
            name_account='Доллары',
            type_account='Debit',
            currency='USD',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        cases = (
            ('foreign account', foreign_source.pk, Decimal('100.00')),
            ('other currency', usd_source.pk, Decimal('100.00')),
            ('negative amount', valid_source.pk, Decimal('-1.00')),
            ('insufficient funds', valid_source.pk, Decimal('1000.01')),
        )

        for case, source_account_id, amount in cases:
            with self.subTest(case=case), self.assertRaises(ValidationError):
                service.create_funded_term_deposit(
                    FundDepositCommand(
                        user=user,
                        name='Недоступный вклад',
                        bank='SBERBANK',
                        currency='RUB',
                        amount=amount,
                        source_account_id=source_account_id,
                        opened_on=date(2026, 8, 1),
                        matures_on=date(2027, 2, 1),
                        annual_rate=Decimal('15.50'),
                    ),
                )

        self.assertFalse(Deposit.objects.filter(account__user=user).exists())
        valid_source.refresh_from_db()
        self.assertEqual(valid_source.balance, Decimal('1000.00'))

    def test_event_failure_rolls_back_funding_and_agreement(self) -> None:
        """If event creation fails, the atomic transaction fully rolls back."""
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()

        with (
            patch.object(
                service.deposit_repository,
                'create_principal_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.create_funded_term_deposit(
                FundDepositCommand(
                    user=user,
                    name='Атомарный вклад',
                    bank='SBERBANK',
                    currency='RUB',
                    amount=Decimal('500.00'),
                    source_account_id=source_account.pk,
                    opened_on=date(2026, 8, 1),
                    matures_on=date(2027, 2, 1),
                    annual_rate=Decimal('15.50'),
                ),
            )

        source_account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('1000.00'))
        self.assertFalse(Deposit.objects.filter(account__user=user).exists())
        self.assertFalse(
            DepositPrincipalEvent.objects.filter(
                deposit__account__user=user,
            ).exists(),
        )

    def test_balance_failure_rolls_back_source_account_change(self) -> None:
        """If deposit account balance update fails, source account
        is unchanged."""
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        original_save = Account.save

        def fail_deposit_balance_save(
            account: Account,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            if (
                account.type_account == ACCOUNT_TYPE_DEPOSIT
                and kwargs.get('update_fields') is not None
            ):
                raise RuntimeError('deposit balance storage failed')
            original_save(account, *args, **kwargs)

        with (
            patch.object(Account, 'save', new=fail_deposit_balance_save),
            self.assertRaises(RuntimeError),
        ):
            service.create_funded_term_deposit(
                FundDepositCommand(
                    user=user,
                    name='Атомарный баланс',
                    bank='SBERBANK',
                    currency='RUB',
                    amount=Decimal('500.00'),
                    source_account_id=source_account.pk,
                    opened_on=date(2026, 8, 1),
                    matures_on=date(2027, 2, 1),
                    annual_rate=Decimal('15.50'),
                ),
            )

        source_account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('1000.00'))
        self.assertFalse(Deposit.objects.filter(account__user=user).exists())
        self.assertFalse(DepositPrincipalEvent.objects.exists())

    def test_open_existing_deposit_records_neutral_opening_position(
        self,
    ) -> None:
        """Opening position does not create transactions, transfers, or affect
        dashboard KPIs (income/expenses/savings rate)."""
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        kpis_before = get_dashboard_month_kpis(user)

        deposit = service.open_existing_term_deposit(
            OpenExistingDepositCommand(
                user=user,
                name='Действующий вклад',
                bank='SBERBANK',
                currency='RUB',
                current_balance=Decimal('75000.00'),
                tracking_started_on=date(2026, 7, 15),
                opened_on=date(2026, 6, 1),
                matures_on=date(2026, 12, 1),
                annual_rate=Decimal('14.00'),
            ),
        )

        self.assertEqual(deposit.account.balance, Decimal('75000.00'))
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(
            event.type,
            DepositPrincipalEvent.Type.OPENING_POSITION,
        )
        self.assertEqual(event.amount, Decimal('75000.00'))
        self.assertEqual(event.effective_on, date(2026, 7, 15))
        self.assertIsNone(event.source_account)
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_create_funded_deposit_preserves_assets_and_records_event(
        self,
    ) -> None:
        """Funding preserves total assets, records a FUNDING event, and does not
        create income/expense transactions."""
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('200000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        kpis_before = get_dashboard_month_kpis(user)

        deposit = service.create_funded_term_deposit(
            FundDepositCommand(
                user=user,
                name='Новый вклад',
                bank='SBERBANK',
                currency='RUB',
                amount=Decimal('150000.00'),
                source_account_id=source_account.pk,
                opened_on=date(2026, 8, 1),
                matures_on=date(2027, 2, 1),
                annual_rate=Decimal('15.50'),
            ),
        )

        source_account.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('50000.00'))
        self.assertEqual(deposit.account.balance, Decimal('150000.00'))
        self.assertEqual(
            source_account.balance + deposit.account.balance,
            Decimal('200000.00'),
        )
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(event.type, DepositPrincipalEvent.Type.FUNDING)
        self.assertEqual(event.amount, Decimal('150000.00'))
        self.assertEqual(event.source_account, source_account)
        self.assertEqual(event.effective_on, date(2026, 8, 1))
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_create_term_deposit_builds_complete_agreement(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()

        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Надёжный доход',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('150000.00'),
                opened_on=date(2026, 8, 1),
                matures_on=date(2027, 2, 1),
                annual_rate=Decimal('15.50'),
            ),
        )

        self.assertIsInstance(deposit, Deposit)
        self.assertEqual(deposit.account.user, user)
        self.assertEqual(deposit.name, 'Надёжный доход')
        self.assertEqual(deposit.bank, 'SBERBANK')
        self.assertEqual(deposit.account.user, user)
        self.assertEqual(deposit.account.type_account, ACCOUNT_TYPE_DEPOSIT)
        self.assertEqual(deposit.account.currency, 'RUB')
        self.assertEqual(deposit.account.balance, Decimal('150000.00'))

        terms = list(deposit.terms.all())
        self.assertEqual(len(terms), 1)
        term = terms[0]
        self.assertTrue(term.is_current)
        self.assertEqual(term.opened_on, date(2026, 8, 1))
        self.assertEqual(term.matures_on, date(2027, 2, 1))

        rate_periods = list(term.rate_periods.all())
        self.assertEqual(len(rate_periods), 1)
        self.assertEqual(rate_periods[0].starts_on, term.opened_on)
        self.assertEqual(rate_periods[0].ends_on, term.matures_on)
        self.assertEqual(rate_periods[0].annual_rate, Decimal('15.50'))
        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(
            event.type,
            DepositPrincipalEvent.Type.OPENING_POSITION,
        )

    def test_regular_account_creation_rejects_deposit_type(self) -> None:
        user = cast('User', UserFactory())

        with self.assertRaisesMessage(
            ValidationError,
            'Счёт вклада можно создать только через сервис вкладов.',
        ):
            Account.objects.create(
                user=user,
                name_account='Обход сервиса',
                type_account=ACCOUNT_TYPE_DEPOSIT,
                bank='SBERBANK',
                currency='RUB',
            )

        self.assertFalse(Account.objects.filter(user=user).exists())

    def test_invalid_dates_do_not_leave_partial_records(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.create_term_deposit(
                CreateDepositCommand(
                    user=user,
                    name='Неверный срок',
                    bank='SBERBANK',
                    currency='RUB',
                    balance=Decimal('1000.00'),
                    opened_on=date(2027, 1, 1),
                    matures_on=date(2026, 1, 1),
                    annual_rate=Decimal('10.00'),
                ),
            )

        self.assertFalse(
            Deposit.objects.filter(account__user=user).exists(),
        )
        self.assertFalse(Account.objects.filter(user=user).exists())


class ConvertAccountToDepositServiceTests(TestCase):
    def test_converts_existing_account_preserving_identity_and_balance(
        self,
    ) -> None:
        """Conversion keeps the same PK, balance, currency, owner, and
        timestamps, and records a neutral opening position."""
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        original_pk = account.pk
        original_created_at = account.created_at
        service = ApplicationContainer().deposits.deposit_service()
        kpis_before = get_dashboard_month_kpis(user)

        deposit = service.convert_account_to_deposit(
            ConvertAccountToDepositCommand(
                user=user,
                account_id=account.pk,
                name='Production вклад',
                bank='SBERBANK',
                opened_on=date(2026, 6, 1),
                matures_on=date(2026, 12, 1),
                annual_rate=Decimal('14.00'),
                converted_on=date(2026, 8, 1),
            ),
        )

        account.refresh_from_db()
        self.assertEqual(account.pk, original_pk)
        self.assertEqual(account.balance, Decimal('75000.00'))
        self.assertEqual(account.currency, 'RUB')
        self.assertEqual(account.user, user)
        self.assertEqual(account.created_at, original_created_at)
        self.assertEqual(account.type_account, ACCOUNT_TYPE_DEPOSIT)
        self.assertEqual(deposit.account_id, original_pk)

        event = DepositPrincipalEvent.objects.get(deposit=deposit)
        self.assertEqual(
            event.type,
            DepositPrincipalEvent.Type.OPENING_POSITION,
        )
        self.assertEqual(event.amount, Decimal('75000.00'))
        self.assertEqual(event.effective_on, date(2026, 8, 1))
        self.assertIsNone(event.source_account)
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())

        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_rejects_foreign_account(self) -> None:
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        account = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.convert_account_to_deposit(
                ConvertAccountToDepositCommand(
                    user=user,
                    account_id=account.pk,
                    name='Попытка чужого счёта',
                    bank='SBERBANK',
                    opened_on=date(2026, 6, 1),
                    matures_on=date(2026, 12, 1),
                    annual_rate=Decimal('14.00'),
                    converted_on=date(2026, 8, 1),
                ),
            )

        account.refresh_from_db()
        self.assertEqual(account.type_account, 'Debit')
        self.assertFalse(Deposit.objects.filter(account=account).exists())

    def test_rejects_account_already_of_deposit_type(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        existing_deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Уже вклад',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 7, 1),
                annual_rate=Decimal('10.00'),
            ),
        )

        with self.assertRaises(ValidationError):
            service.convert_account_to_deposit(
                ConvertAccountToDepositCommand(
                    user=user,
                    account_id=existing_deposit.account_id,
                    name='Повторное преобразование',
                    bank='SBERBANK',
                    opened_on=date(2026, 6, 1),
                    matures_on=date(2026, 12, 1),
                    annual_rate=Decimal('14.00'),
                    converted_on=date(2026, 8, 1),
                ),
            )

        self.assertEqual(
            Deposit.objects.filter(account__user=user).count(),
            1,
        )

    def test_conversion_is_idempotent_on_repeat_run(self) -> None:
        """Repeating the same conversion command does not create a
        second deposit or opening position."""
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        command = ConvertAccountToDepositCommand(
            user=user,
            account_id=account.pk,
            name='Production вклад',
            bank='SBERBANK',
            opened_on=date(2026, 6, 1),
            matures_on=date(2026, 12, 1),
            annual_rate=Decimal('14.00'),
            converted_on=date(2026, 8, 1),
        )
        first_deposit = service.convert_account_to_deposit(command)

        with self.assertRaises(ValidationError):
            service.convert_account_to_deposit(command)

        self.assertEqual(Deposit.objects.filter(account=account).count(), 1)
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(
                deposit=first_deposit,
            ).count(),
            1,
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('75000.00'))

    def test_invalid_agreement_leaves_account_unchanged(self) -> None:
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.convert_account_to_deposit(
                ConvertAccountToDepositCommand(
                    user=user,
                    account_id=account.pk,
                    name='Неверный срок',
                    bank='SBERBANK',
                    opened_on=date(2027, 1, 1),
                    matures_on=date(2026, 1, 1),
                    annual_rate=Decimal('14.00'),
                    converted_on=date(2026, 8, 1),
                ),
            )

        account.refresh_from_db()
        self.assertEqual(account.type_account, 'Debit')
        self.assertFalse(Deposit.objects.filter(account=account).exists())
