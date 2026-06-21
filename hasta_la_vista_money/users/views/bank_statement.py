import logging
import sys
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic.edit import FormView

from hasta_la_vista_money.users.forms import (
    BankStatementUploadForm,
)
from hasta_la_vista_money.users.models import (
    BankStatementUpload,
    User,
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

        try:
            logger.info(
                'Creating bank statement upload for user %s, account %s',
                user.username,
                account.name_account,
            )

            # Create upload record
            upload = BankStatementUpload.objects.create(
                user=user,
                account=account,
                pdf_file=pdf_file,
                status=BankStatementUpload.Status.PENDING,
            )

            logger.info('Created upload record with id=%d', upload.pk)

            task_runner = cast(
                'Any',
                _views_module().process_bank_statement_task,
            )
            task = task_runner.delay(upload.pk)
            logger.info('Started background task with id=%s', task.id)

            # Store upload ID in session for progress tracking
            self.request.session['last_upload_id'] = upload.pk

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
                user=request.user,
            )

            def _decimal_or_none(value):
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
                },
            )

        except BankStatementUpload.DoesNotExist:
            return JsonResponse(
                {'error': 'Upload not found'},
                status=404,
            )
