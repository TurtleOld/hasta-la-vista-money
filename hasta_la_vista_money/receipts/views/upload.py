import sys
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    FormView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins.base import FormErrorHandlingMixin
from hasta_la_vista_money.receipts.forms import (
    UploadImageForm,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    compute_image_hash,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.receipts.views']


class UploadImageView(
    LoginRequiredMixin,
    FormView[UploadImageForm],
    FormErrorHandlingMixin,
):
    """Accept a receipt image and enqueue background processing.

    The view does not block on inference: it computes the file hash, rejects
    duplicates, persists a PendingReceipt + the image, dispatches the Celery
    task and redirects the user back to the receipts list. The background
    worker transitions the row to ``ready`` (or ``failed``) on its own.
    """

    template_name = 'receipts/upload_image.html'
    form_class: type[UploadImageForm] = UploadImageForm
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))  # type: ignore[misc]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form: UploadImageForm) -> HttpResponse:
        request = cast('RequestWithContainer', self.request)
        user = cast('User', request.user)
        account = form.cleaned_data.get('account')
        if account is None:
            messages.error(request, constants.INVALID_FILE_FORMAT)
            return super().form_invalid(form)

        uploaded_files = self._get_uploaded_files()
        if not uploaded_files:
            messages.error(request, constants.INVALID_FILE_FORMAT)
            return super().form_invalid(form)

        pending_receipt_service = (
            request.container.receipts.pending_receipt_service()
        )

        queued_count = 0
        duplicate_count = 0

        for uploaded_file in uploaded_files:
            image_hash = compute_image_hash(uploaded_file)
            uploaded_file.seek(0)

            duplicate = pending_receipt_service.find_duplicate(
                user=user,
                image_hash=image_hash,
            )
            if duplicate is not None:
                duplicate_count += 1
                continue

            try:
                pending_receipt = pending_receipt_service.create_processing_job(
                    user=user,
                    account=account,
                    image_file=uploaded_file,
                    image_hash=image_hash,
                )
            except Exception as exc:
                logger.exception(
                    'Error queuing receipt for processing',
                    error=exc,
                )
                return self.handle_form_error_with_message(
                    form,
                    exc,
                    constants.ERROR_PROCESSING_RECEIPT,
                )

            async_result = _views_module().process_pending_receipt.delay(
                pending_receipt.pk,
            )
            pending_receipt_service.attach_task_id(
                pending_receipt=pending_receipt,
                task_id=async_result.id,
            )
            queued_count += 1

        if queued_count:
            messages.success(
                request,
                _(
                    'Чеков поставлено в обработку: %(count)s. '
                    'Когда распознавание завершится, они появятся в списке.',
                )
                % {'count': queued_count},
            )
        if duplicate_count:
            messages.warning(
                request,
                _('Дубликатов пропущено: %(count)s.')
                % {'count': duplicate_count},
            )
        if not queued_count and duplicate_count:
            messages.warning(request, _('Все выбранные чеки уже загружены.'))
        return redirect('receipts:list')

    def _get_uploaded_files(self) -> list[Any]:
        """Extract all uploaded files from request."""
        return list(self.request.FILES.getlist('file'))
