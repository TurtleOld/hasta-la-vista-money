from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.forms import Form
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    FormView,
)

from hasta_la_vista_money.core.mixins.base import FormErrorHandlingMixin
from hasta_la_vista_money.receipts.forms import (
    PendingReceiptProductFormSet,
    PendingReceiptReviewForm,
)
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
)
from hasta_la_vista_money.receipts.views.base import (
    _validation_error_message,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


class ReviewPendingReceiptView(
    LoginRequiredMixin,
    FormView[Any],
    FormErrorHandlingMixin,
):
    """View for reviewing and editing pending receipt before final save."""

    template_name = 'receipts/review_receipt.html'
    success_url: ClassVar[str] = cast(
        'str',
        reverse_lazy('receipts:list'),
    )  # type: ignore[misc]

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        """Check if pending receipt exists and belongs to user.

        Args:
            request: HTTP request.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            HTTP response.
        """
        pending_receipt = get_object_or_404(
            PendingReceipt,
            pk=kwargs.get('pk'),
        )
        if pending_receipt.user != request.user:
            raise Http404
        if pending_receipt.expires_at < timezone.now():
            messages.error(
                request,
                _(
                    'Время редактирования чека истекло. '
                    'Пожалуйста, загрузите чек заново.',
                ),
            )
            pending_receipt.delete()
            return redirect('receipts:upload')
        if pending_receipt.status != PendingReceiptStatus.READY:
            messages.error(
                request,
                _(
                    'Этот чек ещё не готов к проверке. '
                    'Дождитесь окончания обработки.',
                ),
            )
            return redirect('receipts:list')
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self) -> type[Form]:
        """Get form class for pending receipt review.

        Returns:
            Form class.
        """
        self.form_class = PendingReceiptReviewForm
        return self.form_class

    def get_form_kwargs(self) -> dict[str, Any]:
        """Get form kwargs with receipt data.

        Returns:
            Dictionary with form kwargs.
        """
        kwargs = super().get_form_kwargs()
        pending_receipt = self.get_pending_receipt()
        kwargs['receipt_data'] = pending_receipt.receipt_data
        kwargs['user'] = self.request.user
        kwargs['account'] = pending_receipt.account
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for template.

        Args:
            **kwargs: Keyword arguments.

        Returns:
            Dictionary with context data.
        """
        context = super().get_context_data(**kwargs)
        pending_receipt = self.get_pending_receipt()
        context['pending_receipt'] = pending_receipt

        receipt_data = pending_receipt.receipt_data
        products_data = receipt_data.get('items', [])

        if self.request.method == 'POST':
            product_formset = PendingReceiptProductFormSet(
                self.request.POST,
                initial=products_data,
            )
        else:
            product_formset = PendingReceiptProductFormSet(
                initial=products_data,
            )

        context['product_formset'] = product_formset
        return context

    def get_pending_receipt(self) -> PendingReceipt:
        """Get pending receipt instance.

        Returns:
            PendingReceipt instance.
        """
        return get_object_or_404(
            PendingReceipt,
            pk=self.kwargs.get('pk'),
            user=self.request.user,
        )

    def form_valid(self, form: Form) -> HttpResponse:
        """Handle valid form submission.

        Args:
            form: Validated form.

        Returns:
            HTTP response.
        """
        request = cast('RequestWithContainer', self.request)
        pending_receipt = self.get_pending_receipt()
        product_formset = PendingReceiptProductFormSet(self.request.POST)

        if not product_formset.is_valid():
            return self.form_invalid(form)

        receipt_data = self._build_receipt_data(form, product_formset)
        pending_receipt_service = (
            request.container.receipts.pending_receipt_service()
        )

        updated_pending_receipt = (
            pending_receipt_service.update_pending_receipt(
                pending_receipt=pending_receipt,
                receipt_data=receipt_data,
                account=form.cleaned_data['account'],
            )
        )

        if 'save' in self.request.POST:
            try:
                pending_receipt_service.convert_to_receipt(
                    pending_receipt=updated_pending_receipt,
                )
                messages.success(
                    request,
                    _('Чек успешно сохранён!'),
                )
                return redirect('receipts:list')
            except ValidationError as error:
                error_message = _validation_error_message(error)
                logger.warning(
                    'pending_receipt_validation_failed',
                    error=error_message,
                )
                form.add_error(None, error_message)
                messages.error(request, error_message)
                return self.form_invalid(form)
            except Exception as e:
                logger.exception('Error saving receipt', error=e)
                messages.error(
                    request,
                    _('Ошибка при сохранении чека. Попробуйте ещё раз.'),
                )
                return self.form_invalid(form)
        else:
            messages.success(
                request,
                _(
                    'Изменения сохранены. '
                    'Проверьте данные перед финальным сохранением.',
                ),
            )
            return redirect('receipts:review', pk=updated_pending_receipt.pk)

    def _build_receipt_data(
        self,
        form: Form,
        product_formset: Any,
    ) -> dict[str, Any]:
        """Build receipt data dictionary from form and formset.

        Args:
            form: Receipt review form.
            product_formset: Product formset.

        Returns:
            Dictionary with receipt data.
        """
        receipt_date = form.cleaned_data['receipt_date']
        if isinstance(receipt_date, datetime):
            receipt_date_str = receipt_date.strftime('%d.%m.%Y %H:%M')
        else:
            receipt_date_str = str(receipt_date)

        items = []
        for product_form in product_formset:
            if product_form.cleaned_data and not product_form.cleaned_data.get(
                'DELETE',
                False,
            ):
                nds_sum_value = product_form.cleaned_data.get('nds_sum')
                items.append(
                    {
                        'product_name': product_form.cleaned_data.get(
                            'product_name',
                        ),
                        'category': product_form.cleaned_data.get(
                            'category',
                            '',
                        ),
                        'price': float(
                            product_form.cleaned_data.get('price', 0),
                        ),
                        'quantity': float(
                            product_form.cleaned_data.get('quantity', 0),
                        ),
                        'amount': float(
                            product_form.cleaned_data.get('amount', 0),
                        ),
                        'nds_type': product_form.cleaned_data.get('nds_type'),
                        'nds_sum': (
                            float(nds_sum_value)
                            if nds_sum_value is not None
                            else 0
                        ),
                    },
                )

        return {
            'receipt_date': receipt_date_str,
            'name_seller': form.cleaned_data.get('name_seller', ''),
            'retail_place': form.cleaned_data.get('retail_place'),
            'retail_place_address': form.cleaned_data.get(
                'retail_place_address',
            ),
            'number_receipt': form.cleaned_data.get('number_receipt'),
            'total_sum': float(form.cleaned_data.get('total_sum', 0)),
            'nds10': (
                float(form.cleaned_data.get('nds10', 0))
                if form.cleaned_data.get('nds10')
                else None
            ),
            'nds20': (
                float(form.cleaned_data.get('nds20', 0))
                if form.cleaned_data.get('nds20')
                else None
            ),
            'operation_type': form.cleaned_data.get('operation_type', 0),
            'items': items,
        }
