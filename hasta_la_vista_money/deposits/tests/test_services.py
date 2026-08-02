from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEPOSIT
from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositTerm,
)
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
    def test_withdraws_liquid_principal_to_owned_account_neutrally(
        self,
    ) -> None:
        """A permitted withdrawal moves principal without KPI transactions."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('100.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Ликвидный вклад',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.withdrawal_allowed = True
        term.minimum_withdrawal_amount = Decimal('100.00')
        term.maximum_withdrawal_amount = Decimal('400.00')
        term.minimum_balance = Decimal('700.00')
        term.save()

        service.withdraw_deposit_principal(
            WithdrawDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination_account_id=destination.pk,
                amount=Decimal('300.00'),
                effective_on=date(2026, 8, 1),
            ),
        )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('700.00'))
        self.assertEqual(destination.balance, Decimal('400.00'))
        self.assertEqual(TransferMoneyLog.objects.filter(user=user).count(), 1)
        self.assertFalse(Transaction.objects.filter(user=user).exists())

    def test_rejects_withdrawal_outside_liquid_amount(self) -> None:
        """Limits, currency, ownership, and minimum balance reject changes."""
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        foreign_destination = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Ограниченный вклад',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.withdrawal_allowed = True
        term.minimum_withdrawal_amount = Decimal('100.00')
        term.maximum_withdrawal_amount = Decimal('400.00')
        term.minimum_balance = Decimal('700.00')
        term.save()

        cases = (
            (destination.pk, Decimal('99.00')),
            (destination.pk, Decimal('401.00')),
            (destination.pk, Decimal('350.00')),
            (foreign_destination.pk, Decimal('100.00')),
        )
        for destination_id, amount in cases:
            with (
                self.subTest(destination_id=destination_id, amount=amount),
                self.assertRaises(ValidationError),
            ):
                service.withdraw_deposit_principal(
                    WithdrawDepositCommand(
                        user=user,
                        deposit_id=deposit.pk,
                        destination_account_id=destination_id,
                        amount=amount,
                        effective_on=date(2026, 8, 1),
                    ),
                )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('1000.00'))
        self.assertEqual(destination.balance, Decimal('0.00'))
        self.assertFalse(
            DepositPrincipalEvent.objects.filter(
                type=DepositPrincipalEvent.Type.WITHDRAWAL,
            ).exists(),
        )

    def test_allows_occurred_exception_only_with_reason(self) -> None:
        """An exception records an immutable reason and bypasses terms."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с исключением',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('1000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        with self.assertRaises(ValidationError):
            service.withdraw_deposit_principal(
                WithdrawDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination_account_id=destination.pk,
                    amount=Decimal('500.00'),
                    effective_on=date(2026, 8, 1),
                ),
            )

        event = service.withdraw_deposit_principal(
            WithdrawDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination_account_id=destination.pk,
                amount=Decimal('500.00'),
                effective_on=date(2026, 8, 1),
                exception_reason='Банк подтвердил досрочное снятие.',
            ),
        )

        self.assertEqual(
            event.exception_reason,
            'Банк подтвердил досрочное снятие.',
        )

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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                        rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
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
                rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
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
            rate_kind=DepositTerm.RateKind.FIXED,
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
                    rate_kind=DepositTerm.RateKind.FIXED,
                ),
            )

        account.refresh_from_db()
        self.assertEqual(account.type_account, 'Debit')
        self.assertFalse(Deposit.objects.filter(account=account).exists())

    def test_event_failure_rolls_back_type_change_and_agreement(self) -> None:
        """If opening-position event creation fails mid-conversion, the
        account type change and agreement creation are fully rolled back."""
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

        with (
            patch.object(
                service.deposit_repository,
                'create_principal_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.convert_account_to_deposit(
                ConvertAccountToDepositCommand(
                    user=user,
                    account_id=account.pk,
                    name='Production вклад',
                    bank='SBERBANK',
                    opened_on=date(2026, 6, 1),
                    matures_on=date(2026, 12, 1),
                    annual_rate=Decimal('14.00'),
                    converted_on=date(2026, 8, 1),
                    rate_kind=DepositTerm.RateKind.FIXED,
                ),
            )

        account.refresh_from_db()
        self.assertEqual(account.type_account, 'Debit')
        self.assertEqual(account.balance, Decimal('75000.00'))
        self.assertFalse(Deposit.objects.filter(account=account).exists())

    def test_conversion_preserves_assets_by_currency(self) -> None:
        """Total assets per currency are unchanged by the neutral
        conversion, matching the definition used across the reports."""
        user = cast('User', UserFactory())
        other_rub_account = Account.objects.create(
            user=user,
            name_account='Другой рублёвый счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('30000.00'),
        )
        account = Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank='SBERBANK',
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        assets_before = Decimal(
            Account.objects.filter(
                user=user,
                currency='RUB',
            ).aggregate(total=Sum('balance'))['total']
            or 0,
        )
        service = ApplicationContainer().deposits.deposit_service()

        service.convert_account_to_deposit(
            ConvertAccountToDepositCommand(
                user=user,
                account_id=account.pk,
                name='Production вклад',
                bank='SBERBANK',
                opened_on=date(2026, 6, 1),
                matures_on=date(2026, 12, 1),
                annual_rate=Decimal('14.00'),
                converted_on=date(2026, 8, 1),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        assets_after = Decimal(
            Account.objects.filter(
                user=user,
                currency='RUB',
            ).aggregate(total=Sum('balance'))['total']
            or 0,
        )
        self.assertEqual(assets_before, assets_after)
        other_rub_account.refresh_from_db()
        self.assertEqual(other_rub_account.balance, Decimal('30000.00'))


class AddFloatingRatePeriodServiceTests(TestCase):
    def _open_floating_deposit(
        self,
        user: 'User',
        *,
        opened_on: date | None = None,
        matures_on: date | None = None,
    ) -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        opened_on = opened_on or date(2026, 1, 1)
        matures_on = matures_on or date(2026, 12, 31)
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Плавающий вклад',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('50000.00'),
                opened_on=opened_on,
                matures_on=matures_on,
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FLOATING,
            ),
        )
        return deposit

    def test_add_floating_rate_period_trims_previous_and_appends_new(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        new_period = service.add_floating_rate_period(
            AddFloatingRatePeriodCommand(
                user=user,
                term_id=term.pk,
                starts_on=date(2026, 3, 1),
                annual_rate=Decimal('11.50'),
                note='КС ЦБ РФ повышена',
            ),
        )

        term.refresh_from_db()
        periods = list(term.rate_periods.order_by('starts_on'))
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0].ends_on, date(2026, 2, 28))
        self.assertEqual(periods[0].annual_rate, Decimal('10.00'))
        self.assertEqual(periods[1], new_period)
        self.assertEqual(new_period.starts_on, date(2026, 3, 1))
        self.assertEqual(new_period.ends_on, date(2026, 12, 31))
        self.assertEqual(new_period.annual_rate, Decimal('11.50'))
        self.assertEqual(new_period.note, 'КС ЦБ РФ повышена')

    def test_rejects_period_on_fixed_term(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Фикс вклад',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('10000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2026, 3, 1),
                    annual_rate=Decimal('11.00'),
                    note='попытка',
                ),
            )

    def test_rejects_non_owner(self) -> None:
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=other_user,
                    term_id=term.pk,
                    starts_on=date(2026, 3, 1),
                    annual_rate=Decimal('11.00'),
                    note='чужой',
                ),
            )

    def test_rejects_non_positive_rate(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2026, 3, 1),
                    annual_rate=Decimal(0),
                    note='нулевая ставка',
                ),
            )

    def test_rejects_empty_note(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2026, 3, 1),
                    annual_rate=Decimal('11.00'),
                    note='   ',
                ),
            )

    def test_rejects_non_monotonic_starts_on(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()
        service.add_floating_rate_period(
            AddFloatingRatePeriodCommand(
                user=user,
                term_id=term.pk,
                starts_on=date(2026, 3, 1),
                annual_rate=Decimal('11.00'),
                note='первое изменение',
            ),
        )

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2026, 2, 1),
                    annual_rate=Decimal('12.00'),
                    note='более ранняя дата',
                ),
            )

    def test_rejects_starts_on_outside_term_bounds(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2027, 1, 15),
                    annual_rate=Decimal('11.00'),
                    note='после срока',
                ),
            )

    def test_rejects_period_on_matured_term(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(
            user,
            opened_on=date(2020, 1, 1),
            matures_on=date(2020, 6, 1),
        )
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=term.pk,
                    starts_on=date(2020, 3, 1),
                    annual_rate=Decimal('11.00'),
                    note='после погашения',
                ),
            )

    def test_allows_future_starts_on(self) -> None:
        """A rate change already known in advance can be recorded ahead of
        time — starts_on in the future is allowed."""
        user = cast('User', UserFactory())
        today = timezone.localdate()
        deposit = self._open_floating_deposit(
            user,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=300),
        )
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        new_period = service.add_floating_rate_period(
            AddFloatingRatePeriodCommand(
                user=user,
                term_id=term.pk,
                starts_on=today + timedelta(days=30),
                annual_rate=Decimal('13.00'),
                note='повышение с будущей даты',
            ),
        )

        self.assertEqual(new_period.starts_on, today + timedelta(days=30))

    def test_adding_rate_period_recalculates_unconfirmed_forecast(
        self,
    ) -> None:
        """Changing a term's future rate must recreate its unconfirmed
        forecast so the projection reflects the new rate, without
        requiring the user to trigger a separate manual recalculation."""
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        stale_amount = DepositInterestForecast.objects.get(term=term).amount

        service.add_floating_rate_period(
            AddFloatingRatePeriodCommand(
                user=user,
                term_id=term.pk,
                starts_on=date(2026, 3, 1),
                annual_rate=Decimal('30.00'),
                note='резкое повышение ставки',
            ),
        )

        forecast = DepositInterestForecast.objects.get(term=term)
        self.assertNotEqual(forecast.amount, stale_amount)

    def test_adding_rate_period_preserves_confirmed_forecast_rows(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_floating_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        confirmed = DepositInterestForecast.objects.get(term=term)
        confirmed.confirmed = True
        confirmed.save(update_fields=['confirmed'])

        service.add_floating_rate_period(
            AddFloatingRatePeriodCommand(
                user=user,
                term_id=term.pk,
                starts_on=date(2026, 3, 1),
                annual_rate=Decimal('30.00'),
                note='резкое повышение ставки',
            ),
        )

        confirmed.refresh_from_db()
        self.assertTrue(confirmed.confirmed)
        self.assertEqual(
            DepositInterestForecast.objects.filter(term=term).count(),
            2,
        )


class RecalculateInterestForecastServiceTests(TestCase):
    def _open_fixed_deposit(
        self,
        user: 'User',
        *,
        opened_on: date | None = None,
        matures_on: date | None = None,
        annual_rate: Decimal | None = None,
        balance: Decimal | None = None,
    ) -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад для прогноза',
                bank='SBERBANK',
                currency='RUB',
                balance=balance or Decimal('100000.00'),
                opened_on=opened_on or date(2026, 1, 1),
                matures_on=matures_on or date(2026, 12, 31),
                annual_rate=annual_rate or Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        return deposit

    def test_recalculate_forecast_does_not_affect_balances_or_kpis(
        self,
    ) -> None:
        """Forecasting is purely informational: it must not touch
        Account.balance, create transactions/transfers, or move KPIs."""
        user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()
        balance_before = deposit.account.balance
        kpis_before = get_dashboard_month_kpis(user)

        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, balance_before)
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_recalculate_creates_forecast_lines_for_maturity_schedule(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        lines = service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line.payout_on, date(2026, 12, 31))
        self.assertFalse(line.is_rate_undefined)
        self.assertGreater(line.amount, Decimal(0))
        self.assertFalse(line.confirmed)

    def test_recalculate_replaces_unconfirmed_lines_only(self) -> None:
        """Confirmed forecast rows survive a recalculation untouched;
        unconfirmed rows are replaced with freshly computed ones."""
        user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(user)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        confirmed_line = DepositInterestForecast.objects.get(term=term)
        confirmed_line.confirmed = True
        confirmed_line.save(update_fields=['confirmed'])

        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        remaining = DepositInterestForecast.objects.filter(term=term)
        self.assertEqual(remaining.count(), 2)
        confirmed_line.refresh_from_db()
        self.assertTrue(confirmed_line.confirmed)

    def test_recalculate_marks_undefined_floating_period(self) -> None:
        """A floating term whose known rate periods do not reach maturity
        must report the forecast as undefined, not silently continue the
        last known rate."""
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Плавающий вклад для прогноза',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FLOATING,
            ),
        )
        term = deposit.current_term
        known_rate_period = term.rate_periods.get()
        known_rate_period.ends_on = date(2026, 6, 30)
        known_rate_period.save(update_fields=['ends_on'])

        lines = service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].is_rate_undefined)
        self.assertEqual(lines[0].amount, Decimal('0.00'))

    def test_recalculate_for_missing_term_raises(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.recalculate_forecast(
                RecalculateInterestForecastCommand(user=user, term_id=999999),
            )

    def test_recalculate_for_other_users_term_raises(self) -> None:
        owner = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(owner)
        term = deposit.current_term
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.recalculate_forecast(
                RecalculateInterestForecastCommand(
                    user=other_user,
                    term_id=term.pk,
                ),
            )

    def test_custom_schedule_without_dates_raises(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_fixed_deposit(user)
        term = deposit.current_term
        term.payout_schedule_kind = DepositTerm.PayoutScheduleKind.CUSTOM
        term.save(update_fields=['payout_schedule_kind'])

        with self.assertRaises(ValidationError):
            service.recalculate_forecast(
                RecalculateInterestForecastCommand(user=user, term_id=term.pk),
            )

    def test_monthly_schedule_produces_multiple_lines(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(
            user,
            opened_on=date(2026, 1, 15),
            matures_on=date(2026, 4, 15),
        )
        term = deposit.current_term
        term.payout_schedule_kind = DepositTerm.PayoutScheduleKind.MONTHLY
        term.save(update_fields=['payout_schedule_kind'])
        service = ApplicationContainer().deposits.deposit_service()

        lines = service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1].payout_on, date(2026, 4, 15))

    def test_business_day_roll_marks_tentative_date(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_fixed_deposit(
            user,
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 1, 3),
        )
        term = deposit.current_term
        term.business_day_convention = (
            DepositTerm.BusinessDayConvention.FOLLOWING
        )
        term.accrual_end_included = True
        term.save(
            update_fields=['business_day_convention', 'accrual_end_included'],
        )
        service = ApplicationContainer().deposits.deposit_service()

        lines = service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].payout_on, date(2026, 1, 5))
        self.assertTrue(lines[0].is_date_tentative)
