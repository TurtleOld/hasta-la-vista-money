"""Account opening/closing dates and their form/audit behaviour."""

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.forms import AddAccountForm
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.users.models import User


class AccountLifeDatesModelTest(TestCase):
    """Life dates are optional, explicit and never auto-filled."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='life-dates')

    def test_dates_are_optional(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='Без границ',
            currency='RUB',
        )

        self.assertIsNone(account.opened_on)
        self.assertIsNone(account.closed_on)

    def test_database_rejects_open_after_close(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.create(
                user=self.user,
                name_account='Некорректные границы',
                currency='RUB',
                opened_on=date(2026, 2, 1),
                closed_on=date(2026, 1, 1),
            )

    def test_creation_does_not_copy_created_at(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='Создан сейчас',
            currency='RUB',
        )
        if account.created_at is None:
            self.fail('created_at is missing')
        self.assertEqual(account.created_at.date(), timezone.now().date())
        self.assertIsNone(account.opened_on)

    def test_archive_does_not_invent_close_date(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='Архивируется',
            currency='RUB',
        )
        account.archived_at = timezone.now()
        account.save(update_fields=['archived_at', 'updated_at'])

        self.assertIsNone(account.closed_on)

    def test_life_dates_are_audited(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='История дат',
            currency='RUB',
        )
        account.opened_on = date(2025, 1, 1)
        account.closed_on = date(2026, 1, 1)
        with audit_operation(kind=AuditOperationKind.ACCOUNT_EDIT):
            account.save(update_fields=['opened_on', 'closed_on', 'updated_at'])

        entry = AuditLog.objects.filter(
            model_name='finance_account.Account',
            object_pk=str(account.pk),
            action=AuditLog.Action.UPDATE,
        ).latest('pk')
        self.assertEqual(
            entry.diff['changed']['opened_on']['new'],
            '2025-01-01',
        )
        self.assertEqual(
            entry.diff['changed']['closed_on']['new'],
            '2026-01-01',
        )


class AccountLifeDatesFormTest(TestCase):
    """The existing account form edits both dates without auto-fill."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='life-form')

    def _data(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            'name_account': 'Счёт',
            'type_account': 'Debit',
            'balance': '100.00',
            'currency': 'RUB',
        }
        data.update(overrides)
        return data

    def test_form_accepts_and_saves_dates(self) -> None:
        form = AddAccountForm(
            data=self._data(
                opened_on='2025-01-10',
                closed_on='2025-12-31',
            ),
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()

        self.assertEqual(account.opened_on, date(2025, 1, 10))
        self.assertEqual(account.closed_on, date(2025, 12, 31))

    def test_form_rejects_open_after_close(self) -> None:
        form = AddAccountForm(
            data=self._data(
                opened_on='2025-12-31',
                closed_on='2025-01-10',
            ),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('opened_on', form.errors)

    def test_form_leaves_unknown_dates_unknown(self) -> None:
        form = AddAccountForm(data=self._data(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()
        self.assertIsNone(account.opened_on)
        self.assertIsNone(account.closed_on)

    def test_form_does_not_use_today_as_fallback(self) -> None:
        today = timezone.now().date()
        form = AddAccountForm(
            data=self._data(closed_on=(today - timedelta(days=1)).isoformat()),
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()

        self.assertIsNone(account.opened_on)
        self.assertEqual(account.closed_on, today - timedelta(days=1))
