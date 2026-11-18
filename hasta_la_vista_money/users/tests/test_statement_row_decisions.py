from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
    ReconciliationExpiredError,
)


class StatementRowDecisionFixture(TestCase):
    """A RosDorBank upload with rows a user can defer, exclude or resume."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='rosdorbank.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.service = ApplicationContainer().users.statement_row_link_service()

    def _row(
        self,
        position: int,
        decision: str = BankStatementRow.Decision.AWAITING_MARKUP,
        transaction_type: str = 'expense',
        kind: str = 'card',
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=transaction_type,
            transaction_date=datetime(
                2026,
                3,
                1,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
            amount=Decimal('100.00'),
            description='ПЯТЁРОЧКА',
            source_ref=f'{position}-01.03.2026',
            source_row_position=position,
            kind=kind,
            decision=decision,
        )

    def _assert_no_money_touched(self) -> None:
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())


class DecisionViewTest(StatementRowDecisionFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)

    def _url(self, action: str, row: BankStatementRow) -> str:
        return reverse(
            f'finance_account:bank_statement_row_{action}',
            args=[self.upload.pk, row.pk],
        )

    def test_defer_view_writes_deferred_without_money(self) -> None:
        row = self._row(1)

        response = self.client.post(self._url('defer', row))

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self._assert_no_money_touched()

    def test_exclude_view_requires_reason_in_form(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        response = self.client.post(self._url('exclude', row), {'reason': ' '})

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertFalse(row.decision_audits.exists())

    def test_exclude_view_closes_row_with_reason(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        response = self.client.post(
            self._url('exclude', row),
            {'reason': 'Оплата наличными'},
        )

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXCLUDED)
        self.assertEqual(row.decision_reason, 'Оплата наличными')
        self._assert_no_money_touched()

    def test_resume_view_returns_row_to_processing(self) -> None:
        row = self._row(1)
        self.service.defer(row.pk, self.user.pk)

        response = self.client.post(self._url('resume', row))

        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self._assert_no_money_touched()

    def test_foreign_user_cannot_decide_row(self) -> None:
        row = self._row(1)
        self.client.force_login(
            User.objects.create_user(username='other-viewer'),
        )

        response = self.client.post(self._url('defer', row))

        self.assertEqual(response.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_expired_upload_returns_gone(self) -> None:
        row = self._row(1)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now(),
        )

        response = self.client.post(self._url('defer', row))

        self.assertEqual(response.status_code, 410)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_resume_of_closed_row_returns_conflict(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.NEW)

        response = self.client.post(self._url('resume', row))

        self.assertEqual(response.status_code, 409)


class PagesTest(StatementRowDecisionFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)

    def test_markup_page_offers_defer_and_exclude(self) -> None:
        self._row(1)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_markup',
                args=[self.upload.pk],
            ),
        )

        self.assertContains(response, 'Отложить')
        self.assertContains(response, 'Исключить')

    def test_reconciliation_page_shows_deferred_row_to_resume(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.defer(row.pk, self.user.pk)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'deferred'},
        )

        self.assertContains(response, 'Возобновить')
        self.assertContains(response, 'Отложенные')

    def test_reconciliation_page_keeps_exclude_reason_visible(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.exclude(row.pk, self.user.pk, 'Оплата наличными')

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'excluded'},
        )

        self.assertContains(response, 'Оплата наличными')

    def test_upload_page_asks_to_reupload_cleared_rows(self) -> None:
        self._row(1)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            retention_cleaned_at=timezone.now(),
        )

        response = self.client.get(
            reverse('finance_account:bank_statement_upload'),
        )

        self.assertContains(response, 'Требуется повторная загрузка')

    def test_decision_history_keeps_previous_exclusion_reason(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.exclude(row.pk, self.user.pk, 'Оплата наличными')
        self.service.resume(row.pk, self.user.pk)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'all'},
        )

        self.assertContains(response, 'Оплата наличными')
        self.assertContains(response, 'Исключена')


class ResumeGuardTest(StatementRowDecisionFixture):
    def test_resume_suspended_row_with_linked_movement_is_rejected(
        self,
    ) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=Category.objects.create(
                user=self.user,
                name='Продукты',
                type='expense',
            ),
            type='expense',
            amount=Decimal('100.00'),
            date=timezone.now(),
        )
        BankStatementRow.objects.filter(pk=row.pk).update(
            decision=BankStatementRow.Decision.DEFERRED,
            resume_decision=BankStatementRow.Decision.PENDING,
            transaction=movement,
        )

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(row.transaction, movement)
        self.assertFalse(row.decision_audits.exists())

    def test_repeat_resume_needs_an_audited_suspension(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor=self.user,
            decision=BankStatementRow.Decision.PENDING,
        )

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(row.decision_audits.count(), 1)


class NeedsTransferActionsTest(StatementRowDecisionFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.user)
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитная карта',
            balance=Decimal('0.00'),
            currency='RUB',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
        )
        self.card_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.card,
            pdf_file='card.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def _repayment_row(self, position: int) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.card_upload,
            transaction_type='income',
            transaction_date=datetime(
                2026,
                3,
                1,
                12,
                tzinfo=timezone.get_current_timezone(),
            ),
            amount=Decimal('199.00'),
            description='ПОПОЛНЕНИЕ',
            source_ref=f'{position}-card',
            source_row_position=position,
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )

    def test_account_page_offers_defer_and_exclude_for_repayment(self) -> None:
        self._repayment_row(1)

        response = self.client.get(reverse('finance_account:list'))

        self.assertContains(response, 'Отложить')
        self.assertContains(response, 'Исключить')

    def test_reconciliation_page_offers_actions_for_repayment(self) -> None:
        row = self._repayment_row(1)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.card_upload.pk],
            ),
            {'outcome': 'needs_transfer'},
        )

        self.assertContains(
            response,
            reverse(
                'finance_account:bank_statement_row_defer',
                args=[self.card_upload.pk, row.pk],
            ),
        )
        self.assertContains(
            response,
            reverse(
                'finance_account:bank_statement_row_exclude',
                args=[self.card_upload.pk, row.pk],
            ),
        )
        self.assertContains(response, 'pending-transfers')

    def test_defer_and_exclude_post_for_repayment_rows(self) -> None:
        deferred = self._repayment_row(1)
        excluded = self._repayment_row(2)

        defer_response = self.client.post(
            reverse(
                'finance_account:bank_statement_row_defer',
                args=[self.card_upload.pk, deferred.pk],
            ),
        )
        exclude_response = self.client.post(
            reverse(
                'finance_account:bank_statement_row_exclude',
                args=[self.card_upload.pk, excluded.pk],
            ),
            {'reason': 'Ошибочное зачисление'},
        )

        self.assertEqual(defer_response.status_code, 302)
        self.assertEqual(exclude_response.status_code, 302)
        deferred.refresh_from_db()
        excluded.refresh_from_db()
        self.assertEqual(deferred.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(excluded.decision, BankStatementRow.Decision.EXCLUDED)
        self.assertEqual(excluded.decision_reason, 'Ошибочное зачисление')
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('0.00'))
        self.assertFalse(Transaction.objects.exists())


class MarkupSkipDelegationTest(StatementRowDecisionFixture):
    def test_markup_skip_writes_deferred_with_markup_target(self) -> None:
        row = self._row(1)
        markup = ApplicationContainer().users.statement_markup_service()

        markup.skip(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self._assert_no_money_touched()


class RetentionKeepsDeferredTest(StatementRowDecisionFixture):
    def test_cleanup_keeps_deferred_decision_and_reports_unresolved(
        self,
    ) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.defer(row.pk, self.user.pk)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now(),
        )

        container = ApplicationContainer()
        cleaned = container.users.bank_statement_retention_service()
        self.assertEqual(cleaned.cleanup_expired(), 1)

        row.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertIsNone(row.amount)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertEqual(self.upload.awaiting_decision_count, 1)


class DeferRowTest(StatementRowDecisionFixture):
    def test_defer_awaiting_markup_keeps_money_and_stays_unresolved(
        self,
    ) -> None:
        row = self._row(1)
        before_date = row.transaction_date

        self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(row.transaction_date, before_date)
        self.assertIsNotNone(row.decided_at)
        self._assert_no_money_touched()
        audit = row.decision_audits.get()
        self.assertEqual(audit.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(audit.actor_id, self.user.pk)

    def test_defer_pending_remembers_reconciliation_mechanism(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.PENDING,
        )
        self._assert_no_money_touched()
        self.assertTrue(AuditLog.objects.exists())

    def test_defer_needs_transfer_remembers_repayment_mechanism(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.NEEDS_TRANSFER)

        self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self._assert_no_money_touched()

        self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self._assert_no_money_touched()

    def test_defer_twice_is_idempotent_and_audits_once(self) -> None:
        row = self._row(1)

        self.service.defer(row.pk, self.user.pk)
        self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision_audits.filter(
                decision=BankStatementRow.Decision.DEFERRED,
            ).count(),
            1,
        )
        self._assert_no_money_touched()


class ResumeRowTest(StatementRowDecisionFixture):
    def test_resume_deferred_markup_row_returns_to_markup(self) -> None:
        row = self._row(1)
        self.service.defer(row.pk, self.user.pk)

        self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        # Kept as the proof of the last audited suspension for repeats.
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self._assert_no_money_touched()
        decisions = list(
            row.decision_audits.values_list('decision', flat=True),
        )
        self.assertEqual(
            decisions,
            [
                BankStatementRow.Decision.DEFERRED,
                BankStatementRow.Decision.AWAITING_MARKUP,
            ],
        )

    def test_resume_deferred_pending_row_returns_to_reconciliation(
        self,
    ) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.defer(row.pk, self.user.pk)

        self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self._assert_no_money_touched()

    def test_resume_excluded_row_keeps_reason_in_history(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.exclude(row.pk, self.user.pk, 'Оплата наличными')

        self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(row.decision_reason, '')
        excluded = row.decision_audits.get(
            decision=BankStatementRow.Decision.EXCLUDED,
        )
        self.assertEqual(excluded.reason, 'Оплата наличными')
        self._assert_no_money_touched()

    def test_resume_twice_is_idempotent_after_audited_resume(self) -> None:
        row = self._row(1)
        self.service.defer(row.pk, self.user.pk)
        self.service.resume(row.pk, self.user.pk)

        self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(row.decision_audits.count(), 2)

    def test_exclude_twice_keeps_one_audit_entry(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        self.service.exclude(row.pk, self.user.pk, 'Дубль вручную')
        self.service.exclude(row.pk, self.user.pk, 'Дубль вручную')

        row.refresh_from_db()
        self.assertEqual(
            row.decision_audits.filter(
                decision=BankStatementRow.Decision.EXCLUDED,
            ).count(),
            1,
        )
        self._assert_no_money_touched()

    def test_resume_closed_row_is_rejected(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.NEW)

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.resume(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)


class ExcludeRowTest(StatementRowDecisionFixture):
    def test_exclude_without_reason_changes_nothing(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        for reason in ('', '   '):
            with self.assertRaises(ValidationError):
                self.service.exclude(row.pk, self.user.pk, reason)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertFalse(row.decision_audits.exists())
        self._assert_no_money_touched()

    def test_exclude_with_reason_closes_row_without_money(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)

        self.service.exclude(row.pk, self.user.pk, '  Дубль вручную  ')

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXCLUDED)
        self.assertEqual(row.decision_reason, 'Дубль вручную')
        self.assertEqual(
            row.resume_decision,
            BankStatementRow.Decision.PENDING,
        )
        audit = row.decision_audits.get()
        self.assertEqual(audit.decision, BankStatementRow.Decision.EXCLUDED)
        self.assertEqual(audit.reason, 'Дубль вручную')
        self._assert_no_money_touched()

    def test_exclude_linked_row_is_rejected(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=Category.objects.create(
                user=self.user,
                name='Продукты',
                type='expense',
            ),
            type='expense',
            amount=Decimal('100.00'),
            date=timezone.now(),
        )
        BankStatementRow.objects.filter(pk=row.pk).update(
            transaction=movement,
            decision=BankStatementRow.Decision.NEW,
        )

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.exclude(row.pk, self.user.pk, 'Не учитывать')

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))


class DecisionGuardTest(StatementRowDecisionFixture):
    def test_foreign_row_is_not_found(self) -> None:
        row = self._row(1)
        other = User.objects.create_user(username='other-owner')

        with self.assertRaises(BankStatementRow.DoesNotExist):
            self.service.defer(row.pk, other.pk)
        with self.assertRaises(BankStatementRow.DoesNotExist):
            self.service.exclude(row.pk, other.pk, 'Причина')
        with self.assertRaises(BankStatementRow.DoesNotExist):
            self.service.resume(row.pk, other.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_expired_upload_rejects_decisions_without_change(self) -> None:
        row = self._row(1)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now(),
        )

        with self.assertRaises(ReconciliationExpiredError):
            self.service.defer(row.pk, self.user.pk)
        with self.assertRaises(ReconciliationExpiredError):
            self.service.exclude(row.pk, self.user.pk, 'Причина')

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertFalse(row.decision_audits.exists())

    def test_cleared_upload_requires_reexport_not_a_decision(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            retention_cleaned_at=timezone.now(),
        )

        with self.assertRaises(ReconciliationExpiredError):
            self.service.defer(row.pk, self.user.pk)
        with self.assertRaises(ReconciliationExpiredError):
            self.service.resume(row.pk, self.user.pk)


class UploadStatusTest(StatementRowDecisionFixture):
    def test_deferred_rows_keep_upload_unresolved(self) -> None:
        row = self._row(1)
        self.service.defer(row.pk, self.user.pk)

        self.upload.refresh_from_db()
        self.assertEqual(self.upload.awaiting_decision_count, 1)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )

    def test_excluded_row_is_not_an_open_problem(self) -> None:
        row = self._row(1)
        self.service.exclude(row.pk, self.user.pk, 'Служебная строка')

        self.upload.refresh_from_db()
        self.assertEqual(self.upload.awaiting_decision_count, 0)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED,
        )

    def test_resume_returns_upload_to_unresolved(self) -> None:
        row = self._row(1, decision=BankStatementRow.Decision.PENDING)
        self.service.exclude(row.pk, self.user.pk, 'Служебная строка')
        self.service.resume(row.pk, self.user.pk)

        self.upload.refresh_from_db()
        self.assertEqual(self.upload.awaiting_decision_count, 1)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
