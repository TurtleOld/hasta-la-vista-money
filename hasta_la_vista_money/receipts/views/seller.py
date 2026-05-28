from typing import TYPE_CHECKING, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    UpdateView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import UserAuthMixin
from hasta_la_vista_money.receipts.forms import (
    SellerForm,
)
from hasta_la_vista_money.receipts.models import (
    Seller,
)
from hasta_la_vista_money.receipts.views.base import BaseView

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


class SellerCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[SellerForm],
    CreateView[Seller, SellerForm],
    BaseView,
    UserAuthMixin,
):
    model = Seller
    form_class: type[SellerForm] = SellerForm

    def _wants_json_response(self) -> bool:
        requested_with = self.request.headers.get('x-requested-with', '')
        if requested_with.lower() == 'xmlhttprequest':
            return True
        hx_request = self.request.headers.get('hx-request', '')
        return hx_request.lower() == 'true'

    def form_valid(self, form: SellerForm) -> HttpResponse:
        form.instance.user = cast('User', self.request.user)

        if self._wants_json_response():
            self.object = form.save()
            messages.success(
                self.request,
                constants.SUCCESS_MESSAGE_CREATE_SELLER,
            )
            return JsonResponse({'success': True})

        response = super().form_valid(form)
        messages.success(
            self.request,
            constants.SUCCESS_MESSAGE_CREATE_SELLER,
        )
        return response

    def form_invalid(self, form: SellerForm) -> HttpResponse:
        if self._wants_json_response():
            return JsonResponse(
                {
                    'success': False,
                    'errors': form.errors,
                },
                status=400,
            )
        return super().form_invalid(form)

    def get_success_url(self) -> str:
        return str(reverse_lazy('receipts:list'))


class SellerUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin[SellerForm],
    UpdateView[Seller, SellerForm],
    UserAuthMixin,
):
    model = Seller
    form_class: type[SellerForm] = SellerForm
    template_name = 'receipts/seller_update.html'

    def get_queryset(self):
        return Seller.objects.filter(user=self.request.user)

    def get_success_url(self) -> str:
        return str(reverse_lazy('receipts:list'))

    def form_valid(self, form: SellerForm) -> HttpResponse:
        messages.success(
            self.request,
            constants.SUCCESS_MESSAGE_UPDATE_SELLER,
        )
        return super().form_valid(form)
