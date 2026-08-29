import hashlib
import sys
import uuid
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
    ScanQRForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.services.fns_qr import parse_fns_qr
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

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['upload_form'] = context.pop('form')
        context.setdefault(
            'scan_form',
            ScanQRForm(user=cast('User', self.request.user)),
        )
        return context

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

        processing_service = (
            request.container.receipts.receipt_processing_service()
        )

        queued_count = 0
        duplicate_count = 0

        for uploaded_file in uploaded_files:
            image_hash = compute_image_hash(uploaded_file)
            uploaded_file.seek(0)

            duplicate = processing_service.find_duplicate(
                user=user,
                image_hash=image_hash,
            )
            if duplicate is not None:
                duplicate_count += 1
                continue

            try:
                processing_log = processing_service.create_image_job(
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

            task_id = str(uuid.uuid4())
            processing_service.attach_task_id(
                log=processing_log,
                task_id=task_id,
            )
            _views_module().process_receipt_processing_log.apply_async(
                args=[processing_log.pk],
                task_id=task_id,
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


class ScanQRReceiptView(
    LoginRequiredMixin,
    FormView[ScanQRForm],
    FormErrorHandlingMixin,
):
    """Accept a QR string decoded in-browser and enqueue an FNS lookup.

    Mirrors UploadImageView but skips the image upload + pyzbar decode step
    entirely: the QR is already decoded client-side (camera scan), so only
    the raw QR string and target account are submitted.
    """

    template_name = 'receipts/upload_image.html'
    form_class: type[ScanQRForm] = ScanQRForm
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))  # type: ignore[misc]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['scan_form'] = context.pop('form')
        context.setdefault(
            'upload_form',
            UploadImageForm(user=cast('User', self.request.user)),
        )
        return context

    def form_valid(self, form: ScanQRForm) -> HttpResponse:
        request = cast('RequestWithContainer', self.request)
        user = cast('User', request.user)
        account = form.cleaned_data['account']
        qr_raw = form.cleaned_data['qr_raw']
        fiscal_key = parse_fns_qr(qr_raw).fiscal_key
        image_hash = hashlib.sha256(qr_raw.encode()).hexdigest()

        processing_service = (
            request.container.receipts.receipt_processing_service()
        )

        duplicate = processing_service.find_duplicate(
            user=user,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
        )
        if duplicate is not None:
            processing_service.create_duplicate_qr_job(
                user=user,
                account=account,
                qr_raw=qr_raw,
                image_hash=image_hash,
                fiscal_key=fiscal_key,
            )
            messages.warning(request, _('Этот чек уже загружен.'))
            return redirect('receipts:upload')

        try:
            processing_log = processing_service.create_qr_job(
                user=user,
                account=account,
                qr_raw=qr_raw,
                image_hash=image_hash,
                fiscal_key=fiscal_key,
            )
        except Exception as exc:
            logger.exception(
                'Error queuing scanned receipt for processing',
                error=exc,
            )
            return self.handle_form_error_with_message(
                form,
                exc,
                constants.ERROR_PROCESSING_RECEIPT,
            )

        task_id = str(uuid.uuid4())
        processing_service.attach_task_id(
            log=processing_log,
            task_id=task_id,
        )
        _views_module().process_receipt_processing_log.apply_async(
            args=[processing_log.pk],
            task_id=task_id,
        )
        messages.success(
            request,
            _(
                'Чек поставлен в обработку. Сканер сообщит, когда '
                'проведение завершится.',
            ),
        )
        return redirect('receipts:upload')
