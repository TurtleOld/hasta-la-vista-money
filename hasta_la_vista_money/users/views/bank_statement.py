import logging
import sys
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView
from django.views.generic.edit import FormView

from hasta_la_vista_money.constants import (
    STATEMENT_RECONCILIATION_PAGE_SIZE,
)
from hasta_la_vista_money.users.forms import (
    BankStatementUploadForm,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
    InvalidReconciliationDecisionError,
    ReconciliationDecisionConflictError,
    StaleStatementCandidateError,
)


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.users.views']


class BankStatementUploadView(
    LoginRequiredMixin,
    SuccessMessageMixin[BankStatementUploadForm],
    FormView[BankStatementUploadForm],
):
    """View for uploading bank statements in PDF format."""

    template_name = 'users/bank_statement_upload.html'
    form_class = BankStatementUploadForm
    success_message = _(
        'Банковская выписка загружена и будет обработана в фоновом режиме. '
        'Данные появятся в расходах и доходах в течение нескольких минут.',
    )

    def get_form_kwargs(self) -> dict[str, Any]:
        """Add user to form kwargs."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = cast('User', self.request.user)
        return kwargs

    def form_valid(self, form: BankStatementUploadForm) -> HttpResponse:
        """Process uploaded PDF file asynchronously."""
        logger = logging.getLogger(__name__)
        user = cast('User', self.request.user)
        pdf_file = form.cleaned_data['pdf_file']
        account = form.cleaned_data['account']
        digest = sha256()
        for chunk in pdf_file.chunks():
            digest.update(chunk)
        pdf_file.seek(0)
        file_hash = digest.hexdigest()

        try:
            logger.info(
                'Creating bank statement upload for user %s, account %s',
                user.username,
                account.name_account,
            )

            # Create upload record
            upload, created = BankStatementUpload.objects.get_or_create(
                user=user,
                account=account,
                file_hash=file_hash,
                defaults={
                    'pdf_file': pdf_file,
                    'status': BankStatementUpload.Status.PENDING,
                },
            )

            logger.info('Created upload record with id=%d', upload.pk)

            if created:
                task_runner = cast(
                    'Any',
                    _views_module().process_bank_statement_task,
                )
                task = task_runner.delay(upload.pk)
                logger.info('Started background task with id=%s', task.id)
            else:
                messages.warning(
                    self.request,
                    _('Эта выписка уже была загружена.'),
                )

            # Store upload ID in session for progress tracking
            self.request.session['last_upload_id'] = upload.pk

            if created:
                messages.success(self.request, str(self.success_message))

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception('Error creating upload record')
            messages.error(
                self.request,
                f'Произошла ошибка при загрузке файла: {e!s}',
            )
            return self.form_invalid(form)

        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add extra context data."""
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        context['upload_history'] = (
            BankStatementReconciliationService.upload_history(user.pk)
        )
        # Check if there's an ongoing upload
        last_upload_id = self.request.session.get('last_upload_id')
        if last_upload_id:
            try:
                upload = BankStatementUpload.objects.get(
                    id=last_upload_id,
                    user=user,
                )
                # Show progress if not completed
                if upload.status in [
                    BankStatementUpload.Status.PENDING,
                    BankStatementUpload.Status.PROCESSING,
                    BankStatementUpload.Status.AWAITING_CONFIRMATION,
                ]:
                    context['show_progress'] = True
                    context['upload_id'] = upload.pk
                elif upload.status == BankStatementUpload.Status.COMPLETED:
                    # Clear session if completed
                    self.request.session.pop('last_upload_id', None)
            except BankStatementUpload.DoesNotExist:
                # Clear invalid session data
                self.request.session.pop('last_upload_id', None)
        return context

    def get_success_url(self) -> str:
        """Return URL to redirect after successful upload."""
        # Redirect back to the same page to show progress
        return str(reverse_lazy('users:bank_statement_upload'))


class BankStatementUploadStatusView(LoginRequiredMixin, View):
    """View for checking bank statement upload progress."""

    def get(
        self,
        request: HttpRequest,
        upload_id: int,
    ) -> JsonResponse:
        """Get upload status and progress.

        Args:
            request: HTTP request.
            upload_id: ID of the upload to check.

        Returns:
            JSON response with upload status and progress.
        """
        try:
            upload = BankStatementUpload.objects.get(
                id=upload_id,
                user=cast('User', request.user),
            )

            def _decimal_or_none(value: Decimal | None) -> str | None:
                return str(value) if value is not None else None

            return JsonResponse(
                {
                    'status': upload.status,
                    'progress': upload.progress,
                    'total_transactions': upload.total_transactions,
                    'processed_transactions': upload.processed_transactions,
                    'income_count': upload.income_count,
                    'expense_count': upload.expense_count,
                    'skipped_count': upload.skipped_count,
                    'error_message': upload.error_message,
                    'statement_closing_balance': _decimal_or_none(
                        upload.statement_closing_balance,
                    ),
                    'account_balance_after': _decimal_or_none(
                        upload.account_balance_after,
                    ),
                    'balance_discrepancy': _decimal_or_none(
                        upload.balance_discrepancy,
                    ),
                    'reconciliation_url': (
                        reverse(
                            'users:bank_statement_reconciliation',
                            args=[upload.pk],
                        )
                        if upload.status
                        == BankStatementUpload.Status.AWAITING_CONFIRMATION
                        else None
                    ),
                    'outcomes': {
                        'imported': upload.imported_count,
                        'linked': upload.linked_count,
                        'awaiting_decision': (upload.awaiting_decision_count),
                        'expired': upload.expired_count,
                        'failed': upload.failed_count,
                    },
                },
            )

        except BankStatementUpload.DoesNotExist:
            return JsonResponse(
                {'error': 'Upload not found'},
                status=404,
            )


class BankStatementReconciliationView(
    LoginRequiredMixin,
    DetailView[BankStatementUpload],
):
    template_name = 'users/bank_statement_reconciliation.html'
    context_object_name = 'upload'

    def get_queryset(self) -> QuerySet[BankStatementUpload]:
        user = cast('User', self.request.user)
        return BankStatementUpload.objects.filter(
            user=user,
            account__user=user,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        outcome = self.request.GET.get(
            'outcome',
            BankStatementRow.Decision.PENDING,
        )
        rows = BankStatementReconciliationService.reconciliation_rows(
            self.object,
            outcome,
        )
        if outcome not in BankStatementRow.Decision.values:
            outcome = BankStatementRow.Decision.PENDING
        context['page_obj'] = Paginator(
            rows,
            STATEMENT_RECONCILIATION_PAGE_SIZE,
        ).get_page(
            self.request.GET.get('page'),
        )
        context['outcome'] = outcome
        return context


class BankStatementReconciliationDecisionView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = get_object_or_404(
            BankStatementRow,
            pk=row_id,
            upload_id=upload_id,
            upload__user=request.user,
            upload__account__user=request.user,
        )
        try:
            BankStatementReconciliationService().decide(
                row.pk,
                request.POST.get('decision', ''),
                cast('User', request.user).pk,
                self._candidate_id(request),
            )
        except InvalidReconciliationDecisionError:
            return HttpResponse(status=400)
        except ReconciliationDecisionConflictError:
            return HttpResponse(status=409)
        except StaleStatementCandidateError:
            return self._stale_response(row)
        return redirect(
            reverse(
                'users:bank_statement_reconciliation',
                args=[upload_id],
            ),
        )

    def _candidate_id(self, request: HttpRequest) -> int | None:
        value = request.POST.get('candidate')
        return int(value) if value and value.isdigit() else None

    def _stale_response(self, row: BankStatementRow) -> JsonResponse:
        candidates = BankStatementReconciliationService().current_candidates(
            row,
        )
        return JsonResponse(
            {'candidates': list(candidates.values_list('pk', flat=True))},
            status=409,
        )
