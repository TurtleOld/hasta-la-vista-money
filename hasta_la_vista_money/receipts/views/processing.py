import sys
import uuid
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import View

from hasta_la_vista_money.receipts.models import ReceiptProcessingStatus

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.receipts.views']


class ReceiptProcessingLogRetryView(LoginRequiredMixin, View):
    """Re-enqueue a failed automatic processing attempt."""

    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        user = cast('User', request.user)
        service = cast(
            'RequestWithContainer',
            request,
        ).container.receipts.receipt_processing_service()
        log = service.get_for_user(
            user=user,
            log_id=cast('int', kwargs.get('pk')),
        )
        if log is None:
            return redirect('receipts:list')
        if log.status != ReceiptProcessingStatus.FAILED:
            messages.error(request, _('Повторная обработка недоступна.'))
            return redirect('receipts:list')
        if not log.image_file and not log.qr_raw:
            messages.error(
                request,
                _('Исходные данные чека больше недоступны.'),
            )
            return redirect('receipts:list')
        service.reset_for_retry(log=log)
        task_id = str(uuid.uuid4())
        service.attach_task_id(log=log, task_id=task_id)
        _views_module().process_receipt_processing_log.apply_async(
            args=[log.pk],
            task_id=task_id,
        )
        messages.success(request, _('Чек снова поставлен в обработку.'))
        return redirect('receipts:list')


class ReceiptProcessingNotificationView(LoginRequiredMixin, View):
    """Return newly completed receipts for the scanner notification."""

    http_method_names = ['get']

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        service = cast(
            'RequestWithContainer',
            request,
        ).container.receipts.receipt_processing_service()
        logs = service.get_unnotified_completed(user=cast('User', request.user))
        return JsonResponse(
            {
                'notifications': [
                    {
                        'url': reverse('receipts:view', args=[log.receipt_id]),
                        'message': str(_('Чек проведён. Открыть чек.')),
                    }
                    for log in logs
                ],
            },
        )
