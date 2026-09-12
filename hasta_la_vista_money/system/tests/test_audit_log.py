from datetime import UTC, datetime
from decimal import Decimal

from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.audit_registry import (
    AUDIT_FIELDS,
    HIDDEN_AUDIT_FIELDS,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.system.services.audit_feed import list_operations
from hasta_la_vista_money.system.services.audit_render import (
    NBSP,
    RenderedChange,
    RenderedEntry,
    render_entries,
)
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import User

ACCOUNT_LABEL = 'finance_account.Account'


class AuditLogWriteTests(TestCase):
    """The write layer stores raw attnames and raw values."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='audit-user')

    def test_create_writes_raw_snapshot_with_format_version(self) -> None:
        account = Account.objects.create(
            user=self.user,
            balance=Decimal('100.00'),
        )

        audit_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account.pk),
            action=AuditLog.Action.CREATE,
        )
        self.assertEqual(audit_log.user, self.user)
        self.assertEqual(audit_log.object_name, account.name_account)
        self.assertEqual(audit_log.diff['v'], 2)
        self.assertEqual(audit_log.diff['created']['balance'], '100.00')

    def test_update_writes_raw_attnames(self) -> None:
        account = Account.objects.create(
            user=self.user,
            balance=Decimal('100.00'),
        )

        account.balance = Decimal('75.50')
        account.save()

        audit_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertEqual(audit_log.diff['v'], 2)
        self.assertEqual(
            audit_log.diff['changed']['balance'],
            {'old': '100.00', 'new': '75.50'},
        )

    def test_delete_writes_raw_snapshot(self) -> None:
        account = Account.objects.create(
            user=self.user,
            balance=Decimal('100.00'),
        )
        object_pk = str(account.pk)

        account.delete()

        audit_log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=object_pk,
            action=AuditLog.Action.DELETE,
        )
        self.assertEqual(audit_log.diff['v'], 2)
        self.assertEqual(audit_log.diff['deleted']['balance'], '100.00')

    def test_hidden_field_is_recorded_even_though_it_is_not_shown(
        self,
    ) -> None:
        account = Account.objects.create(user=self.user)

        account.last_reconciled_at = datetime(
            2026,
            3,
            1,
            12,
            0,
            tzinfo=UTC,
        )
        account.save()

        audit_log = AuditLog.objects.filter(
            model_name=ACCOUNT_LABEL,
            object_pk=str(account.pk),
            action=AuditLog.Action.UPDATE,
        ).latest('created_at')
        self.assertIn('updated_at', audit_log.diff['changed'])
        labels = [
            change.label for change in render_entries([audit_log])[0].changes
        ]
        self.assertNotIn('updated_at', labels)


class AuditRegistryConsistencyTests(TestCase):
    """A new model field must be named by the registry or hidden list."""

    def test_registry_covers_every_field_of_audited_models(self) -> None:
        for model_label, fields in AUDIT_FIELDS.items():
            model = apps.get_model(model_label)
            declared = set(fields) | HIDDEN_AUDIT_FIELDS[model_label]
            concrete = {field.attname for field in model._meta.concrete_fields}
            self.assertEqual(
                concrete - declared,
                set(),
                f'{model_label}: поля не описаны в реестре',
            )
            self.assertEqual(
                declared - concrete,
                set(),
                f'{model_label}: реестр описывает несуществующие поля',
            )

    def test_registry_describes_twenty_seven_fields(self) -> None:
        total = sum(len(fields) for fields in AUDIT_FIELDS.values())
        self.assertEqual(total, 27)


class AuditRenderTests(TestCase):
    """The registry is applied on read, to version 2 entries only."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='audit-reader')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Т-Банк',
            currency='RUB',
            balance=Decimal(0),
        )

    def _latest(self, action: str) -> AuditLog:
        return AuditLog.objects.filter(action=action).latest('created_at')

    def test_money_is_printed_with_groups_and_account_currency(self) -> None:
        self.account.balance = Decimal(2494)
        self.account.save()

        rendered = render_entries([self._latest(AuditLog.Action.UPDATE)])[0]
        balance = self._change(rendered, 'Остаток')
        self.assertEqual(balance.new, f'2{NBSP}494,00{NBSP}RUB')

    def test_currency_change_prints_each_side_in_its_own_currency(
        self,
    ) -> None:
        self.account.balance = Decimal(1000)
        self.account.save()
        self.account.currency = 'USD'
        self.account.balance = Decimal(1200)
        self.account.save()

        rendered = render_entries([self._latest(AuditLog.Action.UPDATE)])[0]
        balance = self._change(rendered, 'Остаток')
        self.assertEqual(balance.old, f'1{NBSP}000,00{NBSP}RUB')
        self.assertEqual(balance.new, f'1{NBSP}200,00{NBSP}USD')

    def test_foreign_key_and_choice_are_resolved_on_read(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type='expense',
        )
        transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type='expense',
            date=datetime(2026, 3, 1, 15, 30, tzinfo=UTC),
            amount=Decimal('1279.50'),
        )

        entry = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction.pk),
            action=AuditLog.Action.CREATE,
        )
        rendered = render_entries([entry])[0]
        self.assertEqual(self._change(rendered, 'Счёт').new, 'Т-Банк')
        self.assertEqual(self._change(rendered, 'Категория').new, 'Продукты')
        self.assertEqual(self._change(rendered, 'Тип операции').new, 'Расход')
        self.assertEqual(
            self._change(rendered, 'Сумма').new,
            f'1{NBSP}279,50{NBSP}RUB',
        )

    def test_money_side_follows_the_account_of_that_side(self) -> None:
        other_account = Account.objects.create(
            user=self.user,
            name_account='Валютный',
            currency='USD',
        )
        entry = self._entry(
            'transactions.Transaction',
            {
                'account_id': {
                    'old': other_account.pk,
                    'new': self.account.pk,
                },
                'amount': {'old': '100.00', 'new': '110.00'},
            },
        )

        rendered = render_entries([entry])[0]
        amount = self._change(rendered, 'Сумма')
        self.assertEqual(amount.old, f'100,00{NBSP}USD')
        self.assertEqual(amount.new, f'110,00{NBSP}RUB')

    def test_deleted_reference_is_named_by_its_id(self) -> None:
        entry = self._entry(
            'transactions.Transaction',
            {'account_id': {'old': self.account.pk, 'new': 424242}},
        )

        rendered = render_entries([entry])[0]
        account = self._change(rendered, 'Счёт')
        self.assertEqual(account.old, 'Т-Банк')
        self.assertEqual(account.new, '(удалён, id=424242)')

    def test_unknown_choice_code_is_printed_not_hidden(self) -> None:
        entry = self._entry(
            'receipts.Receipt',
            {'operation_type': {'old': 3, 'new': 7}},
        )

        rendered = render_entries([entry])[0]
        operation = self._change(rendered, 'Тип операции')
        self.assertEqual(operation.old, 'Расход')
        self.assertEqual(operation.new, 'Код 7')

    def test_empty_value_is_printed_as_a_dash(self) -> None:
        entry = self._entry(
            'finance_account.TransferMoneyLog',
            {'notes': {'old': '', 'new': 'Аванс'}},
        )

        rendered = render_entries([entry])[0]
        notes = self._change(rendered, 'Примечание')
        self.assertEqual(notes.old, '—')
        self.assertEqual(notes.new, 'Аванс')

    def test_datetime_is_printed_in_local_time(self) -> None:
        moment = datetime(2026, 3, 1, 15, 30, tzinfo=UTC)
        entry = self._entry(
            'finance_account.TransferMoneyLog',
            {'exchange_date': {'old': None, 'new': moment.isoformat()}},
        )

        rendered = render_entries([entry])[0]
        exchange_date = self._change(rendered, 'Дата перевода')
        self.assertEqual(
            exchange_date.new,
            timezone.localtime(moment).strftime('%d.%m.%Y %H:%M'),
        )

    def _entry(
        self,
        model_name: str,
        changed: dict[str, dict[str, object]],
    ) -> AuditLog:
        return AuditLog.objects.create(
            user=self.user,
            model_name=model_name,
            object_pk='1',
            action=AuditLog.Action.UPDATE,
            diff={'v': 2, 'changed': changed},
        )

    def test_legacy_entry_is_printed_as_it_was_stored(self) -> None:
        entry = AuditLog.objects.create(
            user=self.user,
            model_name=ACCOUNT_LABEL,
            object_pk=str(self.account.pk),
            object_name='Т-Банк',
            action=AuditLog.Action.UPDATE,
            diff={'Баланс': {'old': '100.00', 'new': '75.50'}},
        )

        rendered = render_entries([entry])[0]
        self.assertTrue(rendered.legacy)
        self.assertEqual(len(rendered.changes), 1)
        self.assertEqual(rendered.changes[0].label, 'Баланс')
        self.assertEqual(rendered.changes[0].old, '100.00')
        self.assertEqual(rendered.changes[0].new, '75.50')

    def _change(
        self,
        rendered: RenderedEntry,
        label: str,
    ) -> RenderedChange:
        found = next(
            (change for change in rendered.changes if change.label == label),
            None,
        )
        if found is None:
            self.fail(f'изменение «{label}» не отрисовано')
        return found


class AuditLogViewTests(TestCase):
    """The feed shows operations, not raw entries."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='audit-viewer',
            password='audit-password',
        )
        self.client.force_login(self.user)

    def _make_transfer(
        self,
        *,
        from_name: str = '',
        to_name: str = '',
    ) -> None:
        """Perform one real transfer through the transfer service."""
        container = ApplicationContainer()
        transfer_service = container.finance_account.transfer_service()
        from_account = Account.objects.create(
            user=self.user,
            name_account=from_name,
            balance=Decimal('1000.00'),
        )
        to_account = Account.objects.create(
            user=self.user,
            name_account=to_name,
            balance=Decimal('500.00'),
        )
        AuditLog.objects.filter(user=self.user).delete()
        transfer_service.transfer_money(
            from_account=from_account,
            to_account=to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )

    def _make_single_account_change(
        self,
        *,
        kind: AuditOperationKind,
        balance_before: Decimal,
        balance_after: Decimal,
    ) -> Account:
        """Move one account's balance under a chosen operation kind."""
        account = Account.objects.create(user=self.user, balance=balance_before)
        AuditLog.objects.filter(user=self.user).delete()
        with audit_operation(kind):
            account.balance = balance_after
            account.save()
        return account

    def _make_archival_bucket(self, count: int) -> Account:
        """Write ``count`` operation-id-less updates in the same second."""
        account = Account.objects.create(
            user=self.user,
            name_account='Т-Банк',
        )
        AuditLog.objects.filter(user=self.user).delete()
        created = [
            AuditLog.objects.create(
                user=self.user,
                model_name=ACCOUNT_LABEL,
                object_pk=str(account.pk),
                object_name=account.name_account,
                action=AuditLog.Action.UPDATE,
                diff={
                    'v': 2,
                    'changed': {
                        'balance': {'old': '0.00', 'new': str(index)},
                    },
                },
            )
            for index in range(count)
        ]
        AuditLog.objects.filter(
            pk__in=[entry.pk for entry in created],
        ).update(created_at=created[0].created_at)
        return account

    def test_service_only_change_gives_no_visible_row(self) -> None:
        """A save that only touches hidden fields gives no feed row."""
        account = Account.objects.create(user=self.user)
        AuditLog.objects.filter(user=self.user).delete()

        account.save()

        self.assertTrue(
            AuditLog.objects.filter(
                user=self.user,
                action=AuditLog.Action.UPDATE,
            ).exists(),
        )
        response = self.client.get(reverse('system:auditlog'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['rendered_operations']), [])

    def test_transfer_is_one_operation_titled_perevod(self) -> None:
        """A transfer's three audit entries render as one «Перевод» row."""
        self._make_transfer(from_name='Наличные', to_name='Т-Банк')

        self.assertEqual(
            AuditLog.objects.filter(user=self.user).count(),
            3,
        )
        response = self.client.get(reverse('system:auditlog'))
        operations = response.context['rendered_operations']
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].title, 'Перевод')
        self.assertFalse(operations[0].archival)

    def test_operation_counter_counts_operations_not_entries(self) -> None:
        """The feed counter counts operations, not raw audit entries."""
        self._make_transfer()

        self.assertEqual(
            AuditLog.objects.filter(user=self.user).count(),
            3,
        )
        response = self.client.get(reverse('system:auditlog'))
        self.assertEqual(response.context['paginator'].count, 1)

    def test_archival_entries_glue_into_one_heuristic_operation(
        self,
    ) -> None:
        """Entries without an operation id bucket by owner and second."""
        self._make_archival_bucket(2)

        response = self.client.get(reverse('system:auditlog'))
        operations = response.context['rendered_operations']
        self.assertEqual(len(operations), 1)
        self.assertTrue(operations[0].archival)
        self.assertEqual(
            operations[0].title,
            'Изменение счёта «Т-Банк»',
        )
        self.assertEqual(len(operations[0].entries), 2)

    def test_archival_bucket_over_twelve_collapses_to_mass_change(
        self,
    ) -> None:
        """A bucket past the safety-valve limit collapses to one line."""
        self._make_archival_bucket(13)

        response = self.client.get(reverse('system:auditlog'))
        operations = response.context['rendered_operations']
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertTrue(operation.archival)
        self.assertEqual(operation.collapsed_count, 13)
        self.assertEqual(
            operation.title,
            'Массовое изменение · 13 записей',
        )
        self.assertEqual(operation.entries, [])

    def test_operation_never_splits_across_a_page(self) -> None:
        """A one-page-sized page still returns a whole operation intact."""
        self._make_transfer()
        entries = list(AuditLog.objects.filter(user=self.user))
        self.assertEqual(len(entries), 3)

        operations = list_operations(
            AuditLog.objects.filter(user=self.user),
            page=1,
            page_size=1,
        )
        self.assertEqual(len(operations.operations), 1)
        self.assertEqual(len(operations.operations[0].entries), 3)

    def test_collapsed_bucket_with_no_visible_changes_is_dropped(
        self,
    ) -> None:
        """A >12 bucket whose entries are all hidden fields gives no row."""
        account = Account.objects.create(user=self.user)
        AuditLog.objects.filter(user=self.user).delete()
        created = [
            AuditLog.objects.create(
                user=self.user,
                model_name=ACCOUNT_LABEL,
                object_pk=str(account.pk),
                object_name=account.name_account,
                action=AuditLog.Action.UPDATE,
                diff={
                    'v': 2,
                    'changed': {
                        'updated_at': {
                            'old': str(index),
                            'new': str(index + 1),
                        },
                    },
                },
            )
            for index in range(13)
        ]
        AuditLog.objects.filter(
            pk__in=[entry.pk for entry in created],
        ).update(created_at=created[0].created_at)

        response = self.client.get(reverse('system:auditlog'))
        self.assertEqual(list(response.context['rendered_operations']), [])

    def test_single_account_change_gives_one_chip_and_signed_total(
        self,
    ) -> None:
        """One account moved: one chip, and the total is its movement."""
        self._make_single_account_change(
            kind=AuditOperationKind.INCOME,
            balance_before=Decimal('1000.00'),
            balance_after=Decimal('1500.00'),
        )

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        self.assertEqual(len(operation.balance_chips), 1)
        chip = operation.balance_chips[0]
        self.assertEqual(chip.before, f'1{NBSP}000,00{NBSP}RUB')
        self.assertEqual(chip.after, f'1{NBSP}500,00{NBSP}RUB')
        self.assertEqual(chip.movement, f'+500,00{NBSP}RUB')
        self.assertFalse(chip.negative)
        if operation.total is None:
            self.fail('у операции нет итога')
        self.assertEqual(operation.total.amount, chip.movement)
        self.assertFalse(operation.total.negative)
        self.assertFalse(operation.total.is_shift)

    def test_amount_edit_total_is_marked_as_balance_shift(self) -> None:
        """An amount edit's total is the balance shift, marked as such."""
        self._make_single_account_change(
            kind=AuditOperationKind.TRANSACTION_EDIT,
            balance_before=Decimal('1250.00'),
            balance_after=Decimal('1000.00'),
        )

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        self.assertEqual(len(operation.balance_chips), 1)
        chip = operation.balance_chips[0]
        self.assertTrue(chip.negative)
        if operation.total is None:
            self.fail('у операции нет итога')
        self.assertEqual(operation.total.amount, f'-250,00{NBSP}RUB')
        self.assertTrue(operation.total.negative)
        self.assertTrue(operation.total.is_shift)

    def test_direct_balance_edit_total_is_marked_as_balance_shift(
        self,
    ) -> None:
        """Editing an account's balance field is also an amount edit."""
        self._make_single_account_change(
            kind=AuditOperationKind.ACCOUNT_EDIT,
            balance_before=Decimal('1000.00'),
            balance_after=Decimal('1200.00'),
        )

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        if operation.total is None:
            self.fail('у операции нет итога')
        self.assertEqual(operation.total.amount, f'+200,00{NBSP}RUB')
        self.assertTrue(operation.total.is_shift)

    def test_transfer_gives_two_chips_with_matching_amounts(self) -> None:
        """A transfer gives two chips whose movements cancel out."""
        self._make_transfer(from_name='Наличные', to_name='Т-Банк')

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        self.assertEqual(len(operation.balance_chips), 2)
        by_account = {
            chip.account_name: chip for chip in operation.balance_chips
        }
        from_chip = by_account.get('Наличные')
        to_chip = by_account.get('Т-Банк')
        if from_chip is None or to_chip is None:
            self.fail('чипы построены не для обоих счетов перевода')
        self.assertTrue(from_chip.negative)
        self.assertFalse(to_chip.negative)
        self.assertEqual(from_chip.movement, f'-200,00{NBSP}RUB')
        self.assertEqual(to_chip.movement, f'+200,00{NBSP}RUB')
        if operation.total is None:
            self.fail('у операции нет итога')
        self.assertIsNone(operation.total.negative)
        self.assertEqual(operation.total.amount, f'200,00{NBSP}RUB')
        self.assertFalse(operation.total.is_shift)

    def test_rename_only_change_has_no_balance_chips_or_total(self) -> None:
        """A field edit with no money effect gets no chips and no total."""
        account = Account.objects.create(
            user=self.user,
            name_account='Тинькофф',
            balance=Decimal('100.00'),
        )
        AuditLog.objects.filter(user=self.user).delete()
        with audit_operation(AuditOperationKind.ACCOUNT_EDIT):
            account.name_account = 'Т-Банк'
            account.save()

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        self.assertEqual(operation.balance_chips, [])
        self.assertIsNone(operation.total)

    def test_archival_balance_change_gets_no_chips(self) -> None:
        """A heuristically-glued group never gets a balance chip."""
        self._make_archival_bucket(2)

        response = self.client.get(reverse('system:auditlog'))
        operation = response.context['rendered_operations'][0]
        self.assertTrue(operation.archival)
        self.assertEqual(operation.balance_chips, [])
        self.assertIsNone(operation.total)
