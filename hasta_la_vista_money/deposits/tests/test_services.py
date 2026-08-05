from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEPOSIT
from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    CapitalizeInterestCommand,
    CloseDepositEarlyCommand,
    CloseMaturedDepositCommand,
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    EarlyClosureTerms,
    ForecastEarlyClosureCommand,
    ForecastTerms,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    RenewDepositCommand,
    ReverseDepositEventCommand,
    TopUpDepositCommand,
    TopUpTerms,
    WithdrawalTerms,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositAuditEvent,
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositRenewalEvent,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.reports.services.aggregation import budget_charts
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.services.dashboard_kpis import (
    get_dashboard_month_kpis,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _sberbank() -> Bank:
    bank, _ = Bank.objects.get_or_create(
        code='SBERBANK',
        defaults={'name': 'Сбербанк', 'is_system': True},
    )
    return bank


class DepositServiceIntegrationTests(TestCase):
    def test_reverse_rejects_blank_foreign_repeated_and_compensating_events(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        foreign_user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.open_existing_term_deposit(
            OpenExistingDepositCommand(
                user=user,
                name='Вклад с ошибкой',
                bank=_sberbank(),
                currency='RUB',
                current_balance=Decimal('500.00'),
                tracking_started_on=date(2026, 1, 1),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        original = deposit.principal_events.get()
        other_deposit = service.open_existing_term_deposit(
            OpenExistingDepositCommand(
                user=user,
                name='Другой вклад',
                bank=_sberbank(),
                currency='RUB',
                current_balance=Decimal('100.00'),
                tracking_started_on=date(2026, 1, 1),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        for label, command in (
            (
                'blank',
                ReverseDepositEventCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    event_kind='principal',
                    event_id=original.pk,
                    reason='  ',
                    reversed_on=date(2026, 1, 2),
                ),
            ),
            (
                'foreign',
                ReverseDepositEventCommand(
                    user=foreign_user,
                    deposit_id=deposit.pk,
                    event_kind='principal',
                    event_id=original.pk,
                    reason='Ошибка.',
                    reversed_on=date(2026, 1, 2),
                ),
            ),
            (
                'wrong_deposit',
                ReverseDepositEventCommand(
                    user=user,
                    deposit_id=other_deposit.pk,
                    event_kind='principal',
                    event_id=original.pk,
                    reason='Ошибка.',
                    reversed_on=date(2026, 1, 2),
                ),
            ),
        ):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                service.reverse_deposit_event(command)

        reversal = service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='principal',
                event_id=original.pk,
                reason='Ошибка.',
                reversed_on=date(2026, 1, 2),
            ),
        )
        for event_id in (original.pk, reversal.pk):
            with (
                self.subTest(event_id=event_id),
                self.assertRaises(
                    ValidationError,
                ),
            ):
                service.reverse_deposit_event(
                    ReverseDepositEventCommand(
                        user=user,
                        deposit_id=deposit.pk,
                        event_kind='principal',
                        event_id=event_id,
                        reason='Повтор.',
                        reversed_on=date(2026, 1, 3),
                    ),
                )

    def test_reverse_rolls_back_balances_when_event_storage_fails(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Пополняемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])
        original = service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('250.00'),
                effective_on=date(2026, 6, 30),
            ),
        )

        with (
            patch.object(
                service.deposit_repository,
                'create_principal_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.reverse_deposit_event(
                ReverseDepositEventCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    event_kind='principal',
                    event_id=original.pk,
                    reason='Ошибка.',
                    reversed_on=date(2026, 7, 1),
                ),
            )

        source_account.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('750.00'))
        self.assertEqual(deposit.account.balance, Decimal('750.00'))
        self.assertFalse(hasattr(original, 'reversal'))

    def test_reverse_renewal_keeps_terms_and_restores_previous_term(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Пролонгируемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2025, 1, 1),
                matures_on=date(2025, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        previous_term = deposit.current_term
        renewed_term = service.renew_matured_deposit(
            RenewDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('11.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        original = DepositRenewalEvent.objects.get(renewed_term=renewed_term)

        reversal = service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='renewal',
                event_id=original.pk,
                reason='Условия пролонгации указаны неверно.',
                reversed_on=date(2026, 1, 2),
            ),
        )

        previous_term.refresh_from_db()
        renewed_term.refresh_from_db()
        self.assertTrue(previous_term.is_current)
        self.assertFalse(renewed_term.is_current)
        self.assertTrue(DepositTerm.objects.filter(pk=renewed_term.pk).exists())
        self.assertEqual(reversal.reversal_of, original)
        self.assertEqual(
            reversal.reversal_reason,
            'Условия пролонгации указаны неверно.',
        )

    def test_reverse_planned_close_reopens_deposit_atomically(self) -> None:
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
                name='Закрываемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2025, 1, 1),
                matures_on=date(2025, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(
                user=user,
                term_id=deposit.current_term.pk,
            ),
        )
        forecast = DepositInterestForecast.objects.get(
            term=deposit.current_term,
        )
        closed = service.close_matured_deposit(
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination=(
                    DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                ),
                destination_account_id=destination.pk,
                principal=Decimal('500.00'),
                gross=Decimal('100.00'),
                withholding=Decimal('10.00'),
                net=Decimal('90.00'),
                posting_on=date(2026, 1, 2),
                value_on=date(2026, 1, 2),
                forecast_id=forecast.pk,
            ),
        )

        reversal = service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='principal',
                event_id=closed.principal_event.pk,
                reason='Банк отменил закрытие.',
                reversed_on=date(2026, 1, 3),
            ),
        )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        term = DepositTerm.objects.get(deposit=deposit, is_current=True)
        self.assertEqual(deposit.account.balance, Decimal('500.00'))
        self.assertFalse(deposit.account.is_archived)
        self.assertEqual(destination.balance, Decimal('100.00'))
        self.assertIsNone(term.closed_on)
        self.assertEqual(reversal.reversal_of, closed.principal_event)
        interest_reversal = DepositCapitalizationEvent.objects.get(
            reversal_of=closed.interest_event,
        )
        self.assertEqual(
            interest_reversal.reversal_reason,
            'Банк отменил закрытие.',
        )

        corrected = service.close_matured_deposit(
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination=(
                    DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                ),
                destination_account_id=destination.pk,
                principal=Decimal('500.00'),
                gross=Decimal('80.00'),
                withholding=Decimal('8.00'),
                net=Decimal('72.00'),
                posting_on=date(2026, 1, 4),
                value_on=date(2026, 1, 4),
            ),
        )
        self.assertNotEqual(corrected.principal_event, closed.principal_event)
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(
                deposit=deposit,
                type=DepositPrincipalEvent.Type.PLANNED_CLOSURE,
            ).count(),
            3,
        )

    def test_reverse_interest_restores_balance_and_kpis(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с капитализацией',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(
                user=user,
                term_id=deposit.current_term.pk,
            ),
        )
        forecast = DepositInterestForecast.objects.get(
            term=deposit.current_term,
        )
        original = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('100.00'),
                withholding=Decimal('10.00'),
                net=Decimal('90.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
                reason='Фактическая выплата банка.',
                forecast_id=forecast.pk,
            ),
        )

        reversal = service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='interest',
                event_id=original.pk,
                reason='Банк отменил выплату.',
                reversed_on=date(2026, 7, 2),
            ),
        )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('500.00'))
        self.assertEqual(reversal.reversal_of, original)
        self.assertEqual(reversal.reversal_reason, 'Банк отменил выплату.')
        with patch(
            'hasta_la_vista_money.users.services.dashboard_kpis.timezone.localdate',
            return_value=date(2026, 7, 31),
        ):
            kpis = get_dashboard_month_kpis(user)
        self.assertEqual(kpis['income'], Decimal('0.00'))
        self.assertEqual(kpis['expenses'], Decimal('0.00'))
        self.assertEqual(kpis['net_result'], Decimal('0.00'))
        forecast.refresh_from_db()
        self.assertTrue(forecast.confirmed)

        corrected = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('80.00'),
                withholding=Decimal('8.00'),
                net=Decimal('72.00'),
                posting_on=date(2026, 7, 3),
                value_on=date(2026, 7, 3),
                reason='Исправленная выплата банка.',
            ),
        )
        self.assertIsNone(corrected.forecast)

    def test_reverse_top_up_restores_balances_and_keeps_history(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Пополняемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])
        original = service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('250.00'),
                effective_on=date(2026, 6, 30),
            ),
        )

        reversal = service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='principal',
                event_id=original.pk,
                reason='Пополнение проведено ошибочно.',
                reversed_on=date(2026, 7, 1),
            ),
        )

        source_account.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('1000.00'))
        self.assertEqual(deposit.account.balance, Decimal('500.00'))
        self.assertEqual(reversal.reversal_of, original)
        self.assertEqual(
            reversal.reversal_reason,
            'Пополнение проведено ошибочно.',
        )
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(deposit=deposit).count(),
            3,
        )
        reversal_log = TransferMoneyLog.objects.get(user=user)
        self.assertEqual(reversal_log.from_account, deposit.account)
        self.assertEqual(reversal_log.to_account, source_account)
        self.assertEqual(reversal_log.amount, Decimal('250.00'))

    def test_top_up_transfers_principal_within_term_conditions(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Пополняемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.minimum_top_up_amount = Decimal('100.00')
        term.maximum_top_up_amount = Decimal('300.00')
        term.top_up_deadline = date(2026, 6, 30)
        term.maximum_balance = Decimal('750.00')
        term.save()
        kpis_before = get_dashboard_month_kpis(user)

        event = service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('250.00'),
                effective_on=date(2026, 6, 30),
            ),
        )

        source_account.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('750.00'))
        self.assertEqual(deposit.account.balance, Decimal('750.00'))
        self.assertEqual(event.type, DepositPrincipalEvent.Type.TOP_UP)
        self.assertEqual(event.effective_on, date(2026, 6, 30))
        self.assertEqual(event.source_account, source_account)
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        with self.assertRaises(ProtectedError):
            deposit.delete()
        with self.assertRaises(ProtectedError):
            deposit.account.delete()
        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_top_up_rejects_planned_operations_outside_term_conditions(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с лимитами',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.minimum_top_up_amount = Decimal('100.00')
        term.maximum_top_up_amount = Decimal('300.00')
        term.top_up_deadline = date(2026, 6, 30)
        term.maximum_balance = Decimal('750.00')
        term.save()

        cases = (
            ('disabled', Decimal('100.00'), date(2026, 6, 1), False),
            ('minimum', Decimal('99.99'), date(2026, 6, 1), True),
            ('maximum', Decimal('300.01'), date(2026, 6, 1), True),
            ('deadline', Decimal('100.00'), date(2026, 7, 1), True),
            ('balance', Decimal('251.00'), date(2026, 6, 1), True),
        )
        for case, amount, effective_on, enabled in cases:
            with self.subTest(case=case):
                term.top_up_allowed = enabled
                term.save(update_fields=['top_up_allowed'])
                with self.assertRaises(ValidationError):
                    service.top_up_deposit_principal(
                        TopUpDepositCommand(
                            user=user,
                            deposit_id=deposit.pk,
                            source_account_id=source_account.pk,
                            amount=amount,
                            effective_on=effective_on,
                        ),
                    )
                source_account.refresh_from_db()
                deposit.account.refresh_from_db()
                self.assertEqual(source_account.balance, Decimal('1000.00'))
                self.assertEqual(deposit.account.balance, Decimal('500.00'))

    def test_top_up_exception_requires_reason_and_is_audited(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с исключением',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        with self.assertRaises(ValidationError):
            service.top_up_deposit_principal(
                TopUpDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    source_account_id=source_account.pk,
                    amount=Decimal('100.00'),
                    effective_on=date(2026, 6, 1),
                ),
            )

        event = service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
                exception_reason='Банк принял пополнение вне условий.',
            ),
        )
        self.assertEqual(
            event.exception_reason,
            'Банк принял пополнение вне условий.',
        )

    def test_top_up_rolls_back_balances_when_event_storage_fails(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Атомарное пополнение',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])

        with (
            patch.object(
                service.deposit_repository,
                'create_principal_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.top_up_deposit_principal(
                TopUpDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    source_account_id=source_account.pk,
                    amount=Decimal('100.00'),
                    effective_on=date(2026, 6, 1),
                ),
            )

        source_account.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source_account.balance, Decimal('1000.00'))
        self.assertEqual(deposit.account.balance, Decimal('500.00'))

    def test_top_up_refreshes_future_forecast_without_replacing_confirmed_row(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с прогнозом',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        confirmed = DepositInterestForecast.objects.get(term=term)
        confirmed.confirmed = True
        confirmed.save(update_fields=['confirmed'])

        service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
            ),
        )

        confirmed.refresh_from_db()
        self.assertTrue(confirmed.confirmed)
        self.assertEqual(
            DepositInterestForecast.objects.filter(term=term).count(),
            1,
        )

    def test_top_up_recalculates_future_unconfirmed_forecast(self) -> None:
        user = cast('User', UserFactory())
        source_account = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с будущим прогнозом',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast_before = DepositInterestForecast.objects.get(term=term)

        service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source_account.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
            ),
        )

        forecast_after = DepositInterestForecast.objects.get(term=term)
        self.assertGreater(forecast_after.amount, forecast_before.amount)
        self.assertFalse(forecast_after.confirmed)

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
                bank=_sberbank(),
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
                        bank=_sberbank(),
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
                    bank=_sberbank(),
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
                    bank=_sberbank(),
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
                bank=_sberbank(),
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
            bank=_sberbank(),
            currency='RUB',
            balance=Decimal('200000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        kpis_before = get_dashboard_month_kpis(user)

        deposit = service.create_funded_term_deposit(
            FundDepositCommand(
                user=user,
                name='Новый вклад',
                bank=_sberbank(),
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
                bank=_sberbank(),
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
        self.assertEqual(deposit.bank.code, 'SBERBANK')
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
                bank=_sberbank(),
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
                    bank=_sberbank(),
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
            bank=_sberbank(),
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
                bank=_sberbank(),
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
                    bank=_sberbank(),
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
                bank=_sberbank(),
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
                    bank=_sberbank(),
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
            bank=_sberbank(),
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        command = ConvertAccountToDepositCommand(
            user=user,
            account_id=account.pk,
            name='Production вклад',
            bank=_sberbank(),
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
            bank=_sberbank(),
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
                    bank=_sberbank(),
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
            bank=_sberbank(),
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
                    bank=_sberbank(),
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
            bank=_sberbank(),
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
                bank=_sberbank(),
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
                bank=_sberbank(),
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
                bank=_sberbank(),
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
                bank=_sberbank(),
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
                bank=_sberbank(),
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


class CapitalizeInterestServiceTests(TestCase):
    def _open_deposit(
        self,
        user: 'User',
        *,
        balance: Decimal | None = None,
    ) -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с капитализацией',
                bank=_sberbank(),
                currency='RUB',
                balance=balance or Decimal('100000.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        return deposit

    def test_capitalize_increases_balance_by_net(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        balance_before = deposit.account.balance

        event = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('12000.00'),
                withholding=Decimal('1560.00'),
                net=Decimal('10440.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
                reason='Фактическая выплата по условиям.',
            ),
        )

        deposit.account.refresh_from_db()
        self.assertEqual(
            deposit.account.balance,
            balance_before + Decimal('10440.00'),
        )
        self.assertEqual(event.gross, Decimal('12000.00'))
        self.assertEqual(event.withholding, Decimal('1560.00'))
        self.assertEqual(event.net, Decimal('10440.00'))

    def test_internal_payout_increases_only_destination_balance(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        destination = Account.objects.create(
            user=user,
            name_account='Счёт для процентов',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        deposit_balance_before = deposit.account.balance

        event = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('5000.00'),
                withholding=Decimal('650.00'),
                net=Decimal('4350.00'),
                posting_on=date(2026, 6, 1),
                value_on=date(2026, 6, 1),
                reason='Выплата на собственный счёт.',
                destination=(
                    DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                ),
                destination_account_id=destination.pk,
            ),
        )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, deposit_balance_before)
        self.assertEqual(destination.balance, Decimal('5350.00'))
        self.assertEqual(
            event.destination,
            DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT,
        )
        self.assertEqual(event.destination_account, destination)

    def test_external_payout_does_not_change_tracked_balances(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        account = Account.objects.create(
            user=user,
            name_account='Обычный счёт',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        balances_before = {
            item.pk: item.balance for item in Account.objects.filter(user=user)
        }

        event = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('5000.00'),
                withholding=Decimal('650.00'),
                net=Decimal('4350.00'),
                posting_on=date(2026, 6, 1),
                value_on=date(2026, 6, 1),
                reason='Выплата внешнему получателю.',
                destination=DepositCapitalizationEvent.Destination.EXTERNAL,
            ),
        )

        account.refresh_from_db()
        deposit.account.refresh_from_db()
        balances_after = {
            item.pk: item.balance for item in Account.objects.filter(user=user)
        }
        self.assertEqual(balances_after, balances_before)
        self.assertEqual(
            event.destination,
            DepositCapitalizationEvent.Destination.EXTERNAL,
        )
        self.assertIsNone(event.destination_account)

    def test_internal_payout_does_not_increase_forecast_principal(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        destination = Account.objects.create(
            user=user,
            name_account='Счёт для процентов',
            currency='RUB',
            balance=Decimal(),
        )
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(
                user=user,
                term_id=deposit.current_term.pk,
            ),
        )
        amount_before = DepositInterestForecast.objects.get(
            term=deposit.current_term,
        ).amount

        service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('5000.00'),
                withholding=Decimal('650.00'),
                net=Decimal('4350.00'),
                posting_on=date(2026, 6, 1),
                value_on=date(2026, 6, 1),
                reason='Выплата на собственный счёт.',
                destination=(
                    DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                ),
                destination_account_id=destination.pk,
            ),
        )
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(
                user=user,
                term_id=deposit.current_term.pk,
            ),
        )

        amount_after = DepositInterestForecast.objects.get(
            term=deposit.current_term,
        ).amount
        self.assertEqual(amount_after, amount_before)

    def test_internal_payout_rejects_foreign_or_other_currency_account(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        invalid_accounts = (
            Account.objects.create(
                user=other_user,
                name_account='Чужой счёт',
                currency='RUB',
                balance=Decimal('1000.00'),
            ),
            Account.objects.create(
                user=user,
                name_account='Валютный счёт',
                currency='USD',
                balance=Decimal('1000.00'),
            ),
        )

        for account in invalid_accounts:
            with (
                self.subTest(account=account.name_account),
                self.assertRaises(ValidationError),
            ):
                service.capitalize_interest(
                    CapitalizeInterestCommand(
                        user=user,
                        deposit_id=deposit.pk,
                        gross=Decimal('5000.00'),
                        withholding=Decimal('650.00'),
                        net=Decimal('4350.00'),
                        posting_on=date(2026, 6, 1),
                        value_on=date(2026, 6, 1),
                        reason='Недопустимый счёт.',
                        destination=(
                            DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                        ),
                        destination_account_id=account.pk,
                    ),
                )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('100000.00'))
        self.assertIsNone(deposit.account.archived_at)
        self.assertFalse(
            DepositPrincipalEvent.objects.filter(
                deposit=deposit,
                type=DepositPrincipalEvent.Type.PLANNED_CLOSURE,
            ).exists(),
        )
        self.assertFalse(
            DepositCapitalizationEvent.objects.filter(
                deposit=deposit,
                is_final=True,
            ).exists(),
        )

        self.assertFalse(
            DepositCapitalizationEvent.objects.filter(deposit=deposit).exists(),
        )

    def test_internal_payout_rolls_back_destination_on_event_failure(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        destination = Account.objects.create(
            user=user,
            name_account='Счёт для процентов',
            currency='RUB',
            balance=Decimal('1000.00'),
        )

        with (
            patch.object(
                service.deposit_repository,
                'create_capitalization_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal('5000.00'),
                    withholding=Decimal('650.00'),
                    net=Decimal('4350.00'),
                    posting_on=date(2026, 6, 1),
                    value_on=date(2026, 6, 1),
                    reason='Ошибка сохранения.',
                    destination=(
                        DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                    ),
                    destination_account_id=destination.pk,
                ),
            )

        destination.refresh_from_db()
        self.assertEqual(destination.balance, Decimal('1000.00'))

    def test_capitalize_creates_immutable_event(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)

        event = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('5000.00'),
                withholding=Decimal('650.00'),
                net=Decimal('4350.00'),
                posting_on=date(2026, 6, 1),
                value_on=date(2026, 6, 1),
                reason='Плановая капитализация.',
            ),
        )

        self.assertEqual(
            DepositCapitalizationEvent.objects.filter(deposit=deposit).count(),
            1,
        )
        event.net = Decimal('1.00')
        with self.assertRaisesMessage(
            ValidationError,
            'Подтверждённую выплату процентов нельзя изменить.',
        ):
            event.save()
        with self.assertRaisesMessage(
            ValidationError,
            'Подтверждённую выплату процентов нельзя удалить.',
        ):
            event.delete()

    def test_capitalize_rejects_mismatched_net(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal('1000.00'),
                    withholding=Decimal('100.00'),
                    net=Decimal('800.00'),
                    posting_on=date(2026, 6, 1),
                    value_on=date(2026, 6, 1),
                    reason='Неверные суммы.',
                ),
            )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('100000.00'))
        self.assertFalse(
            DepositCapitalizationEvent.objects.filter(
                deposit=deposit,
            ).exists(),
        )

    def test_capitalize_rejects_negative_amounts(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)

        negative_cases = (
            (Decimal('-1000.00'), Decimal(0), Decimal('-1000.00')),
            (Decimal('1000.00'), Decimal('-100.00'), Decimal('1100.00')),
            (Decimal('1000.00'), Decimal(0), Decimal('-1000.00')),
        )
        for gross, withholding, net in negative_cases:
            with (
                self.subTest(
                    gross=gross,
                    withholding=withholding,
                    net=net,
                ),
                self.assertRaises(ValidationError),
            ):
                service.capitalize_interest(
                    CapitalizeInterestCommand(
                        user=user,
                        deposit_id=deposit.pk,
                        gross=gross,
                        withholding=withholding,
                        net=net,
                        posting_on=date(2026, 6, 1),
                        value_on=date(2026, 6, 1),
                        reason='Отрицательные суммы.',
                    ),
                )

    def test_capitalize_rejects_zero_net(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal(0),
                    withholding=Decimal(0),
                    net=Decimal(0),
                    posting_on=date(2026, 6, 1),
                    value_on=date(2026, 6, 1),
                    reason='Нулевая капитализация.',
                ),
            )

    def test_capitalize_links_to_forecast_and_confirms_it(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        term = deposit.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast = DepositInterestForecast.objects.get(term=term)
        forecast_amount_before = forecast.amount

        event = service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                forecast_id=forecast.pk,
                gross=Decimal('12000.00'),
                withholding=Decimal('1560.00'),
                net=Decimal('10440.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
            ),
        )

        forecast.refresh_from_db()
        self.assertEqual(event.forecast, forecast)
        self.assertTrue(forecast.confirmed)
        self.assertEqual(forecast.amount, forecast_amount_before)

    def test_capitalize_rejects_already_confirmed_forecast(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        term = deposit.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast = DepositInterestForecast.objects.get(term=term)
        forecast.confirmed = True
        forecast.save(update_fields=['confirmed'])

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    forecast_id=forecast.pk,
                    gross=Decimal('12000.00'),
                    withholding=Decimal(0),
                    net=Decimal('12000.00'),
                    posting_on=date(2026, 7, 1),
                    value_on=date(2026, 7, 1),
                ),
            )

    def test_capitalize_rejects_foreign_forecast(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit_a = self._open_deposit(user)
        deposit_b = self._open_deposit(
            user,
            balance=Decimal('50000.00'),
        )
        term_b = deposit_b.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term_b.pk),
        )
        foreign_forecast = DepositInterestForecast.objects.get(term=term_b)

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit_a.pk,
                    forecast_id=foreign_forecast.pk,
                    gross=Decimal('1000.00'),
                    withholding=Decimal(0),
                    net=Decimal('1000.00'),
                    posting_on=date(2026, 7, 1),
                    value_on=date(2026, 7, 1),
                ),
            )

    def test_capitalize_off_schedule_requires_reason(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal('1000.00'),
                    withholding=Decimal(0),
                    net=Decimal('1000.00'),
                    posting_on=date(2026, 7, 1),
                    value_on=date(2026, 7, 1),
                ),
            )

    def test_capitalize_does_not_create_transactions(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('5000.00'),
                withholding=Decimal('650.00'),
                net=Decimal('4350.00'),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
                reason='Плановая капитализация.',
            ),
        )

        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        kpis = get_dashboard_month_kpis(user)
        self.assertEqual(kpis['income'], Decimal('5000.00'))
        self.assertEqual(kpis['expenses'], Decimal('650.00'))
        self.assertEqual(kpis['net_result'], Decimal('4350.00'))
        self.assertEqual(kpis['savings_rate'], Decimal('87.00'))
        cache.clear()
        charts = budget_charts(user)
        self.assertEqual(charts['total_income'], 5000.0)
        self.assertEqual(charts['total_expense'], 650.0)
        self.assertEqual(charts['net_balance'], 4350.0)

    def test_capitalize_rolls_back_on_event_failure(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        balance_before = deposit.account.balance

        with (
            patch.object(
                service.deposit_repository,
                'create_capitalization_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal('5000.00'),
                    withholding=Decimal(0),
                    net=Decimal('5000.00'),
                    posting_on=date(2026, 7, 1),
                    value_on=date(2026, 7, 1),
                    reason='Плановая капитализация.',
                ),
            )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, balance_before)
        self.assertFalse(
            DepositCapitalizationEvent.objects.filter(
                deposit=deposit,
            ).exists(),
        )

    def test_capitalization_affects_forecast_from_value_date(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(user)
        term = deposit.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast_before = DepositInterestForecast.objects.get(term=term)

        service.capitalize_interest(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('12000.00'),
                withholding=Decimal(0),
                net=Decimal('12000.00'),
                posting_on=date(2026, 6, 30),
                value_on=date(2026, 6, 30),
                reason='Полугодовая капитализация.',
            ),
        )

        forecast_after = DepositInterestForecast.objects.get(term=term)
        self.assertGreater(forecast_after.amount, forecast_before.amount)

    def test_capitalize_rejects_foreign_deposit(self) -> None:
        owner = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_deposit(owner)

        with self.assertRaises(ValidationError):
            service.capitalize_interest(
                CapitalizeInterestCommand(
                    user=other_user,
                    deposit_id=deposit.pk,
                    gross=Decimal('1000.00'),
                    withholding=Decimal(0),
                    net=Decimal('1000.00'),
                    posting_on=date(2026, 7, 1),
                    value_on=date(2026, 7, 1),
                    reason='Чужой вклад.',
                ),
            )


class RenewMaturedDepositServiceTests(TestCase):
    def _open_matured_deposit(self, user: 'User') -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        return cast(
            'Deposit',
            service.create_term_deposit(
                CreateDepositCommand(
                    user=user,
                    name='Вклад для пролонгации',
                    bank=_sberbank(),
                    currency='RUB',
                    balance=Decimal('100000.00'),
                    opened_on=timezone.localdate() - timedelta(days=365),
                    matures_on=timezone.localdate(),
                    annual_rate=Decimal('12.00'),
                    rate_kind=DepositTerm.RateKind.FIXED,
                ),
            ),
        )

    def _renewal_command(
        self,
        user: 'User',
        deposit: Deposit,
    ) -> RenewDepositCommand:
        opened_on = timezone.localdate() + timedelta(days=1)
        return RenewDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            opened_on=opened_on,
            matures_on=opened_on + timedelta(days=180),
            annual_rate=Decimal('10.50'),
            rate_kind=DepositTerm.RateKind.FIXED,
        )

    def test_renew_creates_separate_term_rate_and_forecast(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)
        old_term = deposit.current_term
        old_rate = old_term.rate_periods.get()
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(
                user=user,
                term_id=old_term.pk,
            ),
        )
        old_forecasts = list(
            old_term.interest_forecasts.values_list(
                'payout_on',
                'amount',
                'confirmed',
            ),
        )
        principal_event_ids = list(
            DepositPrincipalEvent.objects.filter(deposit=deposit).values_list(
                'pk',
                flat=True,
            ),
        )
        balance_before = deposit.account.balance
        kpis_before = get_dashboard_month_kpis(user)
        command = self._renewal_command(user, deposit)
        custom_payout_on = command.opened_on + timedelta(days=90)
        command = replace(
            command,
            forecast_terms=ForecastTerms(
                payout_schedule_kind=(DepositTerm.PayoutScheduleKind.CUSTOM),
                custom_payout_dates=[custom_payout_on],
                interest_payout_destination=(
                    DepositTerm.PayoutDestination.EXTERNAL
                ),
            ),
            withdrawal_terms=WithdrawalTerms(
                withdrawal_allowed=True,
                minimum_balance=Decimal('50000.00'),
            ),
            top_up_terms=TopUpTerms(top_up_allowed=True),
        )

        new_term = service.renew_matured_deposit(command)

        old_term.refresh_from_db()
        old_rate.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertFalse(old_term.is_current)
        self.assertTrue(new_term.is_current)
        self.assertEqual(deposit.current_term, new_term)
        self.assertEqual(new_term.opened_on, command.opened_on)
        self.assertEqual(new_term.matures_on, command.matures_on)
        self.assertEqual(new_term.rate_kind, command.rate_kind)
        new_rate = new_term.rate_periods.get()
        self.assertEqual(new_rate.starts_on, command.opened_on)
        self.assertEqual(new_rate.ends_on, command.matures_on)
        self.assertEqual(new_rate.annual_rate, command.annual_rate)
        self.assertEqual(
            list(
                new_term.payout_schedule_dates.values_list(
                    'payout_on',
                    flat=True,
                ),
            ),
            [custom_payout_on],
        )
        self.assertEqual(new_term.interest_forecasts.count(), 2)
        self.assertTrue(new_term.withdrawal_allowed)
        self.assertEqual(new_term.minimum_balance, Decimal('50000.00'))
        self.assertTrue(new_term.top_up_allowed)
        self.assertEqual(old_rate.annual_rate, Decimal('12.00'))
        self.assertEqual(
            list(
                old_term.interest_forecasts.values_list(
                    'payout_on',
                    'amount',
                    'confirmed',
                ),
            ),
            old_forecasts,
        )
        self.assertEqual(
            list(
                DepositPrincipalEvent.objects.filter(
                    deposit=deposit,
                ).values_list('pk', flat=True),
            ),
            principal_event_ids,
        )
        self.assertEqual(deposit.account.balance, balance_before)
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        kpis_after = get_dashboard_month_kpis(user)
        for field in ('income', 'expenses', 'net_result', 'savings_rate'):
            with self.subTest(field=field):
                self.assertEqual(kpis_after[field], kpis_before[field])

    def test_renew_rejects_overlap_repeat_and_zero_balance(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        overlap_deposit = self._open_matured_deposit(user)
        overlap_command = replace(
            self._renewal_command(user, overlap_deposit),
            opened_on=timezone.localdate(),
        )
        old_term = overlap_deposit.current_term
        backwards_command = replace(
            self._renewal_command(user, overlap_deposit),
            opened_on=old_term.opened_on - timedelta(days=180),
            matures_on=old_term.opened_on - timedelta(days=1),
        )
        invalid_schedule_command = replace(
            self._renewal_command(user, overlap_deposit),
            forecast_terms=ForecastTerms(
                payout_schedule_kind=DepositTerm.PayoutScheduleKind.CUSTOM,
                custom_payout_dates=[old_term.matures_on],
            ),
        )
        zero_deposit = self._open_matured_deposit(user)
        Account.objects.filter(pk=zero_deposit.account.pk).update(
            balance=Decimal(),
        )

        with self.assertRaises(ValidationError):
            service.renew_matured_deposit(overlap_command)
        with self.assertRaises(ValidationError):
            service.renew_matured_deposit(backwards_command)
        with self.assertRaises(ValidationError):
            service.renew_matured_deposit(invalid_schedule_command)
        self.assertEqual(overlap_deposit.terms.count(), 1)

        command = self._renewal_command(user, overlap_deposit)
        service.renew_matured_deposit(command)
        with self.assertRaises(ValidationError):
            service.renew_matured_deposit(command)
        self.assertEqual(overlap_deposit.terms.count(), 2)

        with self.assertRaises(ValidationError):
            service.renew_matured_deposit(
                self._renewal_command(user, zero_deposit),
            )
        self.assertEqual(zero_deposit.terms.count(), 1)

    def test_renew_rolls_back_term_switch_when_forecast_creation_fails(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)
        old_term = deposit.current_term

        with (
            patch.object(
                service.deposit_repository,
                'create_forecast_lines',
                side_effect=RuntimeError('forecast storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.renew_matured_deposit(
                self._renewal_command(user, deposit),
            )

        old_term.refresh_from_db()
        self.assertTrue(old_term.is_current)
        self.assertEqual(deposit.terms.count(), 1)


class CloseMaturedDepositServiceTests(TestCase):
    def _open_matured_deposit(
        self,
        user: 'User',
        *,
        matures_on: date | None = None,
    ) -> Deposit:
        service = ApplicationContainer().deposits.deposit_service()
        deposit: Deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад к закрытию',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('100000.00'),
                opened_on=timezone.localdate() - timedelta(days=365),
                matures_on=matures_on or timezone.localdate(),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        return deposit

    def test_close_to_owned_account_returns_principal_and_final_interest(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)
        destination = Account.objects.create(
            user=user,
            name_account='Счёт возврата',
            currency='RUB',
            balance=Decimal('1000.00'),
        )

        result = service.close_matured_deposit(
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination=(
                    DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                ),
                destination_account_id=destination.pk,
                principal=Decimal('100000.00'),
                gross=Decimal('12000.00'),
                withholding=Decimal('1560.00'),
                net=Decimal('10440.00'),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
            ),
        )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        term = deposit.current_term
        term.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal())
        self.assertIsNotNone(deposit.account.archived_at)
        self.assertFalse(
            Account.objects.available_for_operations()
            .filter(pk=deposit.account.pk)
            .exists(),
        )
        self.assertEqual(destination.balance, Decimal('111440.00'))
        self.assertEqual(term.state, DepositTerm.State.CLOSED)
        self.assertEqual(term.closed_on, timezone.localdate())
        self.assertEqual(
            result.principal_event.type,
            DepositPrincipalEvent.Type.PLANNED_CLOSURE,
        )
        self.assertEqual(result.principal_event.amount, Decimal('100000.00'))
        self.assertTrue(result.interest_event.is_final)
        self.assertEqual(result.interest_event.gross, Decimal('12000.00'))
        self.assertFalse(Transaction.objects.filter(user=user).exists())
        self.assertFalse(TransferMoneyLog.objects.filter(user=user).exists())
        self.assertFalse(
            DepositInterestForecast.objects.filter(
                term=term,
                confirmed=False,
            ).exists(),
        )

    def test_close_to_external_recipient_changes_no_other_balance_and_reports(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)
        ordinary_account = Account.objects.create(
            user=user,
            name_account='Обычный счёт',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        command = CloseMaturedDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            destination=DepositCapitalizationEvent.Destination.EXTERNAL,
            destination_account_id=None,
            principal=Decimal('100000.00'),
            gross=Decimal('12000.00'),
            withholding=Decimal('1560.00'),
            net=Decimal('10440.00'),
            posting_on=timezone.localdate(),
            value_on=timezone.localdate(),
        )

        first_result = service.close_matured_deposit(command)
        replay_result = service.close_matured_deposit(command)

        deposit.account.refresh_from_db()
        ordinary_account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal())
        self.assertEqual(ordinary_account.balance, Decimal('1000.00'))
        self.assertIsNone(first_result.principal_event.destination_account)
        self.assertIsNone(first_result.interest_event.destination_account)
        self.assertEqual(
            replay_result.principal_event.pk,
            first_result.principal_event.pk,
        )
        self.assertEqual(
            replay_result.interest_event.pk,
            first_result.interest_event.pk,
        )
        with self.assertRaises(ValidationError):
            service.close_matured_deposit(
                replace(
                    command,
                    posting_on=timezone.localdate() + timedelta(days=1),
                ),
            )
        kpis = get_dashboard_month_kpis(user)
        self.assertEqual(kpis['income'], Decimal('12000.00'))
        self.assertEqual(kpis['expenses'], Decimal('1560.00'))
        self.assertEqual(kpis['net_result'], Decimal('10440.00'))
        with self.assertRaises(ValidationError):
            service.confirm_interest_payment(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    gross=Decimal('100.00'),
                    withholding=Decimal(),
                    net=Decimal('100.00'),
                    posting_on=timezone.localdate(),
                    value_on=timezone.localdate(),
                    reason='Недопустимая выплата после закрытия.',
                    destination=(
                        DepositCapitalizationEvent.Destination.EXTERNAL
                    ),
                ),
            )
        self.assertEqual(
            DepositCapitalizationEvent.objects.filter(deposit=deposit).count(),
            1,
        )

    def test_close_rejects_active_term_and_principal_mismatch(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        active_deposit = self._open_matured_deposit(
            user,
            matures_on=timezone.localdate() + timedelta(days=1),
        )
        matured_deposit = self._open_matured_deposit(user)
        invalid_commands = (
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=active_deposit.pk,
                destination=DepositCapitalizationEvent.Destination.EXTERNAL,
                destination_account_id=None,
                principal=Decimal('100000.00'),
                gross=Decimal(),
                withholding=Decimal(),
                net=Decimal(),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
            ),
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=matured_deposit.pk,
                destination=DepositCapitalizationEvent.Destination.EXTERNAL,
                destination_account_id=None,
                principal=Decimal('99999.00'),
                gross=Decimal(),
                withholding=Decimal(),
                net=Decimal(),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
            ),
        )

        for command in invalid_commands:
            with (
                self.subTest(deposit_id=command.deposit_id),
                self.assertRaises(ValidationError),
            ):
                service.close_matured_deposit(command)

        for deposit in (active_deposit, matured_deposit):
            deposit.account.refresh_from_db()
            self.assertEqual(deposit.account.balance, Decimal('100000.00'))
            self.assertIsNone(deposit.account.archived_at)

    def test_close_rejects_foreign_and_wrong_currency_destination(self) -> None:
        user = cast('User', UserFactory())
        other_user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)
        invalid_accounts = (
            Account.objects.create(
                user=other_user,
                name_account='Чужой счёт',
                currency='RUB',
                balance=Decimal(),
            ),
            Account.objects.create(
                user=user,
                name_account='Счёт в долларах',
                currency='USD',
                balance=Decimal(),
            ),
        )

        for account in invalid_accounts:
            with (
                self.subTest(account=account.pk),
                self.assertRaises(ValidationError),
            ):
                service.close_matured_deposit(
                    CloseMaturedDepositCommand(
                        user=user,
                        deposit_id=deposit.pk,
                        destination=(
                            DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT
                        ),
                        destination_account_id=account.pk,
                        principal=Decimal('100000.00'),
                        gross=Decimal(),
                        withholding=Decimal(),
                        net=Decimal(),
                        posting_on=timezone.localdate(),
                        value_on=timezone.localdate(),
                    ),
                )

    def test_close_rolls_back_balance_and_events_on_interest_failure(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = self._open_matured_deposit(user)

        with (
            patch.object(
                service.deposit_repository,
                'create_capitalization_event',
                side_effect=RuntimeError('interest storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.close_matured_deposit(
                CloseMaturedDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination=DepositCapitalizationEvent.Destination.EXTERNAL,
                    destination_account_id=None,
                    principal=Decimal('100000.00'),
                    gross=Decimal('1000.00'),
                    withholding=Decimal(),
                    net=Decimal('1000.00'),
                    posting_on=timezone.localdate(),
                    value_on=timezone.localdate(),
                ),
            )

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('100000.00'))


class CloseDepositEarlyServiceTests(TestCase):
    def _open_active_deposit(self, user: 'User') -> Deposit:
        today = timezone.localdate()
        service = ApplicationContainer().deposits.deposit_service()
        return cast(
            'Deposit',
            service.create_term_deposit(
                CreateDepositCommand(
                    user=user,
                    name='Вклад для досрочного закрытия',
                    bank=_sberbank(),
                    currency='RUB',
                    balance=Decimal('100000.00'),
                    opened_on=today - timedelta(days=180),
                    matures_on=today + timedelta(days=180),
                    annual_rate=Decimal('12.00'),
                    rate_kind=DepositTerm.RateKind.FIXED,
                    early_closure_terms=EarlyClosureTerms(
                        annual_rate=Decimal('1.00'),
                        recalculation_scope=(
                            DepositTerm.EarlyClosureRecalculationScope.WHOLE_TERM
                        ),
                    ),
                ),
            ),
        )

    def test_forecast_has_no_financial_effects(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_active_deposit(user)
        service = ApplicationContainer().deposits.deposit_service()
        balance_before = deposit.account.balance
        kpis_before = get_dashboard_month_kpis(user)

        result = service.forecast_early_closure(
            ForecastEarlyClosureCommand(
                user=user,
                deposit_id=deposit.pk,
                closure_on=timezone.localdate(),
            ),
        )

        deposit.account.refresh_from_db()
        self.assertEqual(result.principal, Decimal('100000.00'))
        self.assertIsNotNone(result.gross)
        self.assertFalse(result.is_uncertain)
        self.assertEqual(deposit.account.balance, balance_before)
        self.assertEqual(get_dashboard_month_kpis(user), kpis_before)
        self.assertFalse(Transaction.objects.filter(user=user).exists())

    def test_close_preserves_previous_payout_and_counts_adjustment_once(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_active_deposit(user)
        service = ApplicationContainer().deposits.deposit_service()
        previous = service.confirm_interest_payment(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('1000.00'),
                withholding=Decimal('130.00'),
                net=Decimal('870.00'),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
                reason='Промежуточная выплата.',
                destination=(DepositCapitalizationEvent.Destination.EXTERNAL),
            ),
        )

        result = service.close_deposit_early(
            CloseDepositEarlyCommand(
                user=user,
                deposit_id=deposit.pk,
                destination=(DepositCapitalizationEvent.Destination.EXTERNAL),
                destination_account_id=None,
                principal=Decimal('100000.00'),
                gross=Decimal('500.00'),
                withholding=Decimal('65.00'),
                net=Decimal('435.00'),
                prior_interest_adjustment=Decimal('-750.00'),
                posting_on=timezone.localdate(),
                value_on=timezone.localdate(),
                closure_reason='Досрочное расторжение по заявлению клиента.',
            ),
        )

        deposit.account.refresh_from_db()
        deposit.current_term.refresh_from_db()
        previous.refresh_from_db()
        self.assertEqual(
            result.principal_event.type,
            DepositPrincipalEvent.Type.EARLY_CLOSURE,
        )
        self.assertEqual(
            result.principal_event.exception_reason,
            'Досрочное расторжение по заявлению клиента.',
        )
        self.assertEqual(
            result.interest_event.prior_interest_adjustment,
            Decimal('-750.00'),
        )
        self.assertTrue(
            DepositCapitalizationEvent.objects.filter(pk=previous.pk).exists(),
        )
        self.assertEqual(previous.gross, Decimal('1000.00'))
        self.assertEqual(deposit.account.balance, Decimal())
        self.assertTrue(deposit.account.is_archived)
        self.assertEqual(deposit.current_term.state, DepositTerm.State.CLOSED)
        kpis = get_dashboard_month_kpis(user)
        self.assertEqual(kpis['income'], Decimal('1500.00'))
        self.assertEqual(kpis['expenses'], Decimal('945.00'))
        self.assertEqual(kpis['net_result'], Decimal('555.00'))
        cache.clear()
        charts = budget_charts(user, period='y')
        self.assertEqual(charts['total_income'], 1500.0)
        self.assertEqual(charts['total_expense'], 945.0)

        service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='principal',
                event_id=result.principal_event.pk,
                reason='Досрочное закрытие отменено банком.',
                reversed_on=timezone.localdate(),
            ),
        )

        reversed_kpis = get_dashboard_month_kpis(user)
        self.assertEqual(reversed_kpis['income'], Decimal('1750.00'))
        self.assertEqual(reversed_kpis['expenses'], Decimal('880.00'))
        self.assertEqual(reversed_kpis['net_result'], Decimal('870.00'))
        cache.clear()
        reversed_charts = budget_charts(user, period='y')
        self.assertEqual(reversed_charts['total_income'], 1750.0)
        self.assertEqual(reversed_charts['total_expense'], 880.0)

    def test_close_rolls_back_when_final_event_storage_fails(self) -> None:
        user = cast('User', UserFactory())
        deposit = self._open_active_deposit(user)
        service = ApplicationContainer().deposits.deposit_service()

        with (
            patch.object(
                service.deposit_repository,
                'create_capitalization_event',
                side_effect=RuntimeError('interest storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.close_deposit_early(
                CloseDepositEarlyCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination=(
                        DepositCapitalizationEvent.Destination.EXTERNAL
                    ),
                    destination_account_id=None,
                    principal=Decimal('100000.00'),
                    gross=Decimal(),
                    withholding=Decimal(),
                    net=Decimal(),
                    prior_interest_adjustment=Decimal(),
                    posting_on=timezone.localdate(),
                    value_on=timezone.localdate(),
                    closure_reason='Закрытие с проверкой rollback.',
                ),
            )

        deposit.account.refresh_from_db()
        deposit.current_term.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('100000.00'))
        self.assertFalse(deposit.account.is_archived)
        self.assertEqual(deposit.current_term.state, DepositTerm.State.ACTIVE)
        self.assertFalse(
            DepositPrincipalEvent.objects.filter(
                deposit=deposit,
                type=DepositPrincipalEvent.Type.EARLY_CLOSURE,
            ).exists(),
        )


def _withdrawal_test_deposit(
    user: 'User',
    *,
    name: str = 'Вклад с частичным снятием',
    minimum_balance: Decimal = Decimal(),
) -> Deposit:
    service = ApplicationContainer().deposits.deposit_service()
    deposit = cast(
        'Deposit',
        service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name=name,
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        ),
    )
    term = deposit.current_term
    term.withdrawal_allowed = True
    term.minimum_balance = minimum_balance
    term.save(update_fields=['withdrawal_allowed', 'minimum_balance'])
    return deposit


class WithdrawDepositPrincipalServiceTests(TestCase):
    def test_exception_withdrawal_below_minimum_balance_succeeds(
        self,
    ) -> None:
        """Снятие с указанной причиной обходит проверку неснижаемого
        остатка и создаёт событие с exception_reason."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = _withdrawal_test_deposit(
            user,
            minimum_balance=Decimal('400.00'),
        )

        command = WithdrawDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            destination_account_id=destination.pk,
            amount=Decimal('450.00'),
            effective_on=date(2026, 6, 1),
            exception_reason='Экстренная выплата по решению клиента.',
        )
        event = service.withdraw_deposit_principal(command)

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('50.00'))
        self.assertEqual(destination.balance, Decimal('450.00'))
        self.assertEqual(
            event.exception_reason,
            'Экстренная выплата по решению клиента.',
        )
        self.assertTrue(
            DepositAuditEvent.objects.filter(
                deposit=deposit,
                event_type=DepositAuditEvent.Type.EXCLUSION,
            ).exists(),
        )

    def test_withdrawal_below_minimum_balance_without_reason_fails(
        self,
    ) -> None:
        """Без exception_reason проверка неснижаемого остатка остаётся
        в силе и блокирует снятие."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = _withdrawal_test_deposit(
            user,
            minimum_balance=Decimal('400.00'),
        )

        command = WithdrawDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            destination_account_id=destination.pk,
            amount=Decimal('450.00'),
            effective_on=date(2026, 6, 1),
        )
        with self.assertRaises(ValidationError):
            service.withdraw_deposit_principal(command)

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('500.00'))

    def test_exception_withdrawal_cannot_go_negative(self) -> None:
        """Даже с exception_reason снятие не может увести баланс
        счёта вклада в отрицательное значение."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = _withdrawal_test_deposit(
            user,
            minimum_balance=Decimal('400.00'),
        )

        command = WithdrawDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            destination_account_id=destination.pk,
            amount=Decimal('600.00'),
            effective_on=date(2026, 6, 1),
            exception_reason='Попытка увести в минус.',
        )
        with self.assertRaises(ValidationError):
            service.withdraw_deposit_principal(command)

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('500.00'))

    def test_withdrawal_recalculates_future_unconfirmed_forecast(
        self,
    ) -> None:
        """Снятие тела вклада пересчитывает будущий непотверждённый
        прогноз выплат процентов в меньшую сторону."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = _withdrawal_test_deposit(
            user,
            name='Вклад с будущим прогнозом',
        )
        term = deposit.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast_before = DepositInterestForecast.objects.get(term=term)

        service.withdraw_deposit_principal(
            WithdrawDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination_account_id=destination.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
            ),
        )

        forecast_after = DepositInterestForecast.objects.get(term=term)
        self.assertLess(forecast_after.amount, forecast_before.amount)
        self.assertFalse(forecast_after.confirmed)


class WithdrawDepositPrincipalRollbackTransactionTests(TransactionTestCase):
    def test_withdrawal_rolls_back_on_failure_with_real_transactions(
        self,
    ) -> None:
        """При сбое записи события снятия внутри атомарной операции
        полностью откатываются баланс, событие и прогноз — без частичных
        записей."""
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = _withdrawal_test_deposit(
            user,
            name='Вклад с rollback в реальной транзакции',
        )
        term = deposit.current_term
        service.recalculate_forecast(
            RecalculateInterestForecastCommand(user=user, term_id=term.pk),
        )
        forecast_before = DepositInterestForecast.objects.get(
            term=term,
        ).amount

        with (
            patch.object(
                service.deposit_repository,
                'create_principal_event',
                side_effect=RuntimeError('event storage failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            service.withdraw_deposit_principal(
                WithdrawDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination_account_id=destination.pk,
                    amount=Decimal('100.00'),
                    effective_on=date(2026, 6, 1),
                ),
            )

        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('500.00'))
        self.assertEqual(destination.balance, Decimal('0.00'))
        self.assertFalse(
            DepositPrincipalEvent.objects.filter(
                deposit=deposit,
                type=DepositPrincipalEvent.Type.WITHDRAWAL,
            ).exists(),
        )
        self.assertEqual(
            DepositInterestForecast.objects.get(term=term).amount,
            forecast_before,
        )


class ExternalIdIdempotencyTests(TestCase):
    def test_top_up_with_external_id_is_idempotent(self) -> None:
        user = cast('User', UserFactory())
        source = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с внешним ID',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])

        command = TopUpDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            source_account_id=source.pk,
            amount=Decimal('100.00'),
            effective_on=date(2026, 6, 1),
            external_id='bank-txn-001',
        )
        first = service.top_up_deposit_principal(command)
        second = service.top_up_deposit_principal(command)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(
                deposit=deposit,
                type=DepositPrincipalEvent.Type.TOP_UP,
            ).count(),
            1,
        )
        self.assertEqual(
            DepositPrincipalEvent.objects.filter(deposit=deposit).count(),
            2,
        )
        source.refresh_from_db()
        deposit.account.refresh_from_db()
        self.assertEqual(source.balance, Decimal('900.00'))
        self.assertEqual(deposit.account.balance, Decimal('600.00'))
        self.assertEqual(first.external_id, 'bank-txn-001')

    def test_top_up_with_external_id_rejects_mismatch(self) -> None:
        user = cast('User', UserFactory())
        source = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с внешним ID',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.top_up_allowed = True
        term.save(update_fields=['top_up_allowed'])

        service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
                external_id='bank-txn-002',
            ),
        )

        with self.assertRaises(ValidationError):
            service.top_up_deposit_principal(
                TopUpDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    source_account_id=source.pk,
                    amount=Decimal('200.00'),
                    effective_on=date(2026, 6, 1),
                    external_id='bank-txn-002',
                ),
            )

    def test_withdrawal_with_external_id_is_idempotent(self) -> None:
        user = cast('User', UserFactory())
        destination = Account.objects.create(
            user=user,
            name_account='Получатель',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('100.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с внешним ID',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        term = deposit.current_term
        term.withdrawal_allowed = True
        term.save(update_fields=['withdrawal_allowed'])

        command = WithdrawDepositCommand(
            user=user,
            deposit_id=deposit.pk,
            destination_account_id=destination.pk,
            amount=Decimal('100.00'),
            effective_on=date(2026, 6, 1),
            external_id='wdrw-001',
        )
        first = service.withdraw_deposit_principal(command)
        second = service.withdraw_deposit_principal(command)

        self.assertEqual(first.pk, second.pk)
        deposit.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('400.00'))
        self.assertEqual(destination.balance, Decimal('200.00'))

    def test_interest_payment_with_external_id_is_idempotent(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с внешним ID',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        command = CapitalizeInterestCommand(
            user=user,
            deposit_id=deposit.pk,
            gross=Decimal('100.00'),
            withholding=Decimal('10.00'),
            net=Decimal('90.00'),
            posting_on=date(2026, 7, 1),
            value_on=date(2026, 7, 1),
            reason='Выплата банка.',
            external_id='int-001',
        )
        first = service.confirm_interest_payment(command)
        second = service.confirm_interest_payment(command)

        self.assertEqual(first.pk, second.pk)
        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('590.00'))


class ReconciliationTests(TestCase):
    def test_reconcile_balance_matches_account(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Сверяемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        result = service.reconcile_deposit(deposit.pk, user)
        self.assertEqual(
            result['calculated_balance'],
            Decimal('500.00'),
        )
        self.assertEqual(result['account_balance'], Decimal('500.00'))
        self.assertEqual(result['discrepancy'], Decimal())
        self.assertIsNotNone(result['last_reconciled_at'])

    def test_reconcile_after_capitalization_matches(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Сверяемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.confirm_interest_payment(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('100.00'),
                withholding=Decimal('10.00'),
                net=Decimal('90.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
                reason='Выплата.',
            ),
        )

        result = service.reconcile_deposit(deposit.pk, user)
        self.assertEqual(result['calculated_balance'], Decimal('590.00'))
        self.assertEqual(result['account_balance'], Decimal('590.00'))
        self.assertEqual(result['discrepancy'], Decimal())

    def test_reconcile_after_reversal_matches(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Сверяемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        event = service.confirm_interest_payment(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('100.00'),
                withholding=Decimal('10.00'),
                net=Decimal('90.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
                reason='Выплата.',
            ),
        )
        service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='interest',
                event_id=event.pk,
                reason='Ошибка.',
                reversed_on=date(2026, 7, 2),
            ),
        )

        result = service.reconcile_deposit(deposit.pk, user)
        self.assertEqual(result['calculated_balance'], Decimal('500.00'))
        self.assertEqual(result['account_balance'], Decimal('500.00'))
        self.assertEqual(result['discrepancy'], Decimal())


class AuditEventTests(TestCase):
    def test_conversion_creates_audit_event(self) -> None:
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Production вклад',
            type_account='Debit',
            bank=_sberbank(),
            currency='RUB',
            balance=Decimal('75000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.convert_account_to_deposit(
            ConvertAccountToDepositCommand(
                user=user,
                account_id=account.pk,
                name='Production вклад',
                bank=_sberbank(),
                opened_on=date(2026, 6, 1),
                matures_on=date(2026, 12, 1),
                annual_rate=Decimal('14.00'),
                converted_on=date(2026, 8, 1),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        audit = deposit.audit_events.get()
        self.assertEqual(
            audit.event_type,
            DepositAuditEvent.Type.CONVERSION,
        )

    def test_renewal_creates_audit_event(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Пролонгируемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2025, 1, 1),
                matures_on=date(2025, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.renew_matured_deposit(
            RenewDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('11.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

        audit = deposit.audit_events.get()
        self.assertEqual(
            audit.event_type,
            DepositAuditEvent.Type.RENEWAL,
        )

    def test_closure_creates_audit_event(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Закрываемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2025, 1, 1),
                matures_on=date(2025, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.close_matured_deposit(
            CloseMaturedDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                destination=(DepositCapitalizationEvent.Destination.EXTERNAL),
                destination_account_id=None,
                principal=Decimal('500.00'),
                gross=Decimal(),
                withholding=Decimal(),
                net=Decimal(),
                posting_on=date(2026, 1, 2),
                value_on=date(2026, 1, 2),
            ),
        )

        audit = deposit.audit_events.filter(
            event_type=DepositAuditEvent.Type.CLOSURE,
        ).first()
        if audit is None:
            self.fail('No closure audit event found')
        self.assertEqual(
            audit.event_type,
            DepositAuditEvent.Type.CLOSURE,
        )

    def test_reversal_creates_audit_event(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Аннулируемый вклад',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        event = service.confirm_interest_payment(
            CapitalizeInterestCommand(
                user=user,
                deposit_id=deposit.pk,
                gross=Decimal('100.00'),
                withholding=Decimal('10.00'),
                net=Decimal('90.00'),
                posting_on=date(2026, 7, 1),
                value_on=date(2026, 7, 1),
                reason='Выплата.',
            ),
        )
        service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=user,
                deposit_id=deposit.pk,
                event_kind='interest',
                event_id=event.pk,
                reason='Аннулирование.',
                reversed_on=date(2026, 7, 2),
            ),
        )

        audit = deposit.audit_events.filter(
            event_type=DepositAuditEvent.Type.CANCELLATION,
        ).first()
        if audit is None:
            self.fail('No cancellation audit event found')
        self.assertEqual(
            audit.event_type,
            DepositAuditEvent.Type.CANCELLATION,
        )

    def test_exclusion_top_up_creates_audit_event(self) -> None:
        user = cast('User', UserFactory())
        source = Account.objects.create(
            user=user,
            name_account='Основной счёт',
            type_account='Debit',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        service = ApplicationContainer().deposits.deposit_service()
        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Вклад с исключением',
                bank=_sberbank(),
                currency='RUB',
                balance=Decimal('500.00'),
                opened_on=date(2026, 1, 1),
                matures_on=date(2026, 12, 31),
                annual_rate=Decimal('12.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=user,
                deposit_id=deposit.pk,
                source_account_id=source.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 6, 1),
                exception_reason='Банк принял пополнение вне условий.',
            ),
        )

        audit = deposit.audit_events.filter(
            event_type=DepositAuditEvent.Type.EXCLUSION,
        ).first()
        if audit is None:
            self.fail('No exclusion audit event found')
        self.assertEqual(
            audit.event_type,
            DepositAuditEvent.Type.EXCLUSION,
        )
