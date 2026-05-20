import sys
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    View,
)

from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.receipts.views']


class PendingReceiptRetryView(LoginRequiredMixin, View):
    """Re-enqueue a failed pending receipt without re-uploading the file."""

    http_method_names: ClassVar[list[str]] = ['post']

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        pending = get_object_or_404(
            PendingReceipt,
            pk=kwargs.get('pk'),
            user=request.user,
        )
        if pending.status != PendingReceiptStatus.FAILED:
            messages.error(
                request,
                _('Повторная обработка возможна только для упавших чеков.'),
            )
            return redirect('receipts:list')
        if not pending.image_file:
            messages.error(
                request,
                _('Файл чека больше не доступен. Загрузите чек заново.'),
            )
            return redirect('receipts:list')

        container_request = cast('RequestWithContainer', request)
        service = container_request.container.receipts.pending_receipt_service()
        service.reset_for_retry(pending_receipt=pending)
        async_result = _views_module().process_pending_receipt.delay(pending.pk)
        service.attach_task_id(
            pending_receipt=pending,
            task_id=async_result.id,
        )
        messages.success(
            request,
            _('Чек снова поставлен в обработку.'),
        )
        return redirect('receipts:list')


class PendingReceiptDeleteView(LoginRequiredMixin, View):
    """Delete a pending receipt entry along with its stored image."""

    http_method_names: ClassVar[list[str]] = ['post']

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        pending = get_object_or_404(
            PendingReceipt,
            pk=kwargs.get('pk'),
            user=request.user,
        )
        container_request = cast('RequestWithContainer', request)
        service = container_request.container.receipts.pending_receipt_service()
        service.delete_with_file(pending_receipt=pending)
        messages.success(request, _('Запись удалена.'))
        return redirect('receipts:list')


class PendingReceiptCounterView(LoginRequiredMixin, View):
    """Return the count of receipts currently being processed.

    Used by an HTMX poller next to the upload button so the user sees how
    many uploads are still in flight without reloading the page.
    """

    http_method_names: ClassVar[list[str]] = ['get']
    template_name = 'receipts/_pending_counter.html'

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        count = PendingReceipt.objects.filter(
            user=request.user,
            status=PendingReceiptStatus.PROCESSING,
        ).count()
        return render(request, self.template_name, {'count': count})
