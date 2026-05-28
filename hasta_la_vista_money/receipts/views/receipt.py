from typing import TYPE_CHECKING, Any, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, QuerySet

from hasta_la_vista_money.core.types import RequestWithContainer

if TYPE_CHECKING:
    from django.forms import ModelChoiceField
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    DeleteView,
    DetailView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import UserAuthMixin
from hasta_la_vista_money.core.views import (
    BaseEntityCreateView,
    BaseEntityUpdateView,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import (
    ProductFormSet,
    ReceiptForm,
)
from hasta_la_vista_money.receipts.models import (
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.views.base import BaseView
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


class ReceiptCreateView(
    BaseEntityCreateView[Receipt, ReceiptForm],
    BaseView,
    UserAuthMixin,
):
    model = Receipt
    form_class = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_CREATE_RECEIPT

    def setup(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().setup(request, *args, **kwargs)
        self.request = cast('RequestWithContainer', request)

    def get_form(
        self,
        form_class: type[ReceiptForm] | None = None,
    ) -> ReceiptForm:
        form = super().get_form(form_class)
        if self.request is None:
            raise ValueError('Request is not set')
        current_user = cast('User', self.request.user)
        account_field = cast(
            'ModelChoiceField[Account]',
            form.fields['account'],
        )
        account_field.queryset = Account.objects.by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField[Seller]', form.fields['seller'])
        seller_field.queryset = Seller.objects.for_user(current_user)
        return form

    @staticmethod
    def check_exist_receipt(
        request: RequestWithContainer,
        receipt_form: ReceiptForm,
    ) -> QuerySet[Receipt]:
        number_receipt = receipt_form.cleaned_data.get('number_receipt')
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        receipt_repository = request.container.receipts.receipt_repository()
        return cast(
            'QuerySet[Receipt, Receipt]',
            receipt_repository.get_by_user_and_number(
                user=request.user,
                number_receipt=number_receipt,
            ),
        )

    @staticmethod
    def create_receipt(
        request: RequestWithContainer,
        receipt_form: ReceiptForm,
        product_formset: 'ProductFormSet',  # type: ignore[valid-type]
        seller: Seller,
    ) -> Receipt | None:
        receipt_creator_service = (
            request.container.receipts.receipt_creator_service()
        )
        result = receipt_creator_service.create_manual_receipt(
            user=cast('User', request.user),
            receipt_form=receipt_form,
            product_formset=product_formset,
            seller=seller,
        )
        return cast('Receipt | None', result)

    def form_valid_receipt(
        self,
        receipt_form: ReceiptForm,
        product_formset: 'ProductFormSet',  # type: ignore[valid-type]
        seller: Seller,
    ) -> bool:
        request = cast('RequestWithContainer', self.request)
        number_receipt = self.check_exist_receipt(
            request,
            receipt_form,
        )
        if number_receipt:
            messages.error(
                request,
                _(constants.RECEIPT_ALREADY_EXISTS),
            )
            return False
        self.create_receipt(
            request,
            receipt_form,
            product_formset,
            seller,
        )
        messages.success(
            self.request,
            constants.SUCCESS_MESSAGE_CREATE_RECEIPT,
        )
        return True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        context['receipt_form'] = self.get_form()
        context['product_formset'] = ProductFormSet()
        return context

    def form_valid(self, form: ReceiptForm) -> HttpResponse:  # type: ignore[override]
        seller = cast('Seller', form.cleaned_data.get('seller'))
        product_formset = ProductFormSet(self.request.POST)

        valid_form = form.is_valid() and product_formset.is_valid()
        if valid_form:
            success = self.form_valid_receipt(
                receipt_form=form,
                product_formset=product_formset,
                seller=seller,
            )
            if success:
                return super().form_valid(form)
            return self.form_invalid(form)
        return self.form_invalid(form)

    def form_invalid(self, form: ReceiptForm) -> HttpResponse:
        product_formset = ProductFormSet(self.request.POST)
        context: dict[str, Any] = self.get_context_data(form=form)
        context['product_formset'] = product_formset
        return self.render_to_response(context)

    def get_absolute_url(self) -> str:
        return str(reverse_lazy('receipts:list'))


class ReceiptUpdateView(
    BaseEntityUpdateView[Receipt, ReceiptForm],
    BaseView,
    UserAuthMixin,
):
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm
    template_name: str = 'receipts/receipt_update.html'
    success_message: str = str(constants.SUCCESS_MESSAGE_UPDATE_RECEIPT)

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        try:
            request = cast('RequestWithContainer', self.request)
            receipt_repository = request.container.receipts.receipt_repository()
            receipt = receipt_repository.get_by_id(self.kwargs['pk'])
            if receipt.user != self.request.user:
                raise Http404('Receipt not found')
        except Receipt.DoesNotExist:
            logger.exception('Receipt not found', pk=self.kwargs['pk'])
            raise
        return cast('Receipt', receipt)

    def _setup_form_querysets(self, form: ReceiptForm) -> None:
        request = cast('RequestWithContainer', self.request)
        current_user = cast('User', request.user)
        account_repository = (
            request.container.finance_account.account_repository()
        )
        seller_repository = request.container.receipts.seller_repository()
        account_field = cast(
            'ModelChoiceField[Account]',
            form.fields['account'],
        )
        account_field.queryset = account_repository.get_by_user_with_related(
            current_user,
        )
        seller_field = cast(
            'ModelChoiceField[Seller]',
            form.fields['seller'],
        )
        seller_field.queryset = seller_repository.get_by_user(current_user)

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        if hasattr(self, 'object') and self.object and self.object.seller:
            initial['retail_place'] = self.object.seller.retail_place
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        receipt_form = self.get_form()
        self._setup_form_querysets(receipt_form)

        context['receipt_form'] = receipt_form

        existing_products = self.object.product.all()
        initial_data: list[dict[str, Any]] = [
            {
                'product_name': product.product_name,
                'category': product.category,
                'price': product.price,
                'quantity': product.quantity,
                'amount': product.amount,
            }
            for product in existing_products
        ]
        context['product_formset'] = ProductFormSet(initial=initial_data)
        return context

    def get_form(
        self,
        form_class: type[ReceiptForm] | None = None,
    ) -> ReceiptForm:
        form = super().get_form(form_class)
        self._setup_form_querysets(form)
        return form

    def form_valid(self, form: ReceiptForm) -> HttpResponse:  # type: ignore[override]
        receipt = self.get_object()
        product_formset = ProductFormSet(self.request.POST)
        request = cast('RequestWithContainer', self.request)
        current_user = cast('User', request.user)

        self._setup_form_querysets(form)

        if form.is_valid() and product_formset.is_valid():
            receipt_updater_service = (
                request.container.receipts.receipt_updater_service()
            )
            receipt_updater_service.update_receipt(
                user=current_user,
                receipt=receipt,
                form=form,
                product_formset=product_formset,
            )

            seller = form.cleaned_data.get('seller')
            if seller is not None:
                seller.retail_place = form.cleaned_data.get(
                    'retail_place'
                ) or str(_('Нет данных'))
                seller.save(update_fields=['retail_place'])

            return super().form_valid(form)
        return self.form_invalid(form)

    def form_invalid(self, form: ReceiptForm) -> HttpResponse:
        product_formset = ProductFormSet(self.request.POST)
        context: dict[str, Any] = self.get_context_data(form=form)
        context['product_formset'] = product_formset

        if not form.is_valid():
            messages.error(
                self.request,
                _('Пожалуйста, исправьте ошибки в форме.'),
            )
        if not product_formset.is_valid():
            messages.error(
                self.request,
                _('Пожалуйста, исправьте ошибки в товарах.'),
            )

        return self.render_to_response(context)


class ReceiptDetailView(
    LoginRequiredMixin,
    DetailView[Receipt],
    BaseView,
    UserAuthMixin,
):
    model = Receipt
    template_name: str = 'receipts/receipt_view.html'
    context_object_name: str = 'receipt'

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        request = cast('RequestWithContainer', self.request)
        receipt_repository = request.container.receipts.receipt_repository()
        receipt = (
            receipt_repository.get_by_user_with_related(self.request.user)
            .filter(pk=self.kwargs['pk'])
            .first()
        )
        if receipt is None:
            raise Http404('Receipt not found')
        return cast('Receipt', receipt)


class ReceiptDeleteView(
    LoginRequiredMixin,
    DeleteView[Receipt, Any],
    BaseView,
    UserAuthMixin,
):
    model = Receipt
    success_url = reverse_lazy('receipts:list')

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        request = cast('RequestWithContainer', self.request)
        receipt_repository = request.container.receipts.receipt_repository()
        receipt = (
            receipt_repository.get_by_user_with_related(self.request.user)
            .filter(pk=self.kwargs['pk'])
            .first()
        )
        if receipt is None:
            raise Http404('Receipt not found')
        return cast('Receipt', receipt)

    def get_success_url(self) -> str:
        return str(self.success_url)

    def post(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> HttpResponse:
        receipt = self.get_object()
        request_with_container = cast('RequestWithContainer', request)
        receipt_deleter_service = (
            request_with_container.container.receipts.receipt_deleter_service()
        )

        try:
            receipt_deleter_service.delete_receipt(
                user=cast('User', self.request.user),
                receipt=receipt,
            )
            messages.success(
                self.request,
                constants.SUCCESS_MESSAGE_DELETE_RECEIPT,
            )
            return redirect(str(self.success_url))
        except ProtectedError:
            messages.error(
                self.request,
                constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT,
            )
            return redirect(str(self.success_url))
        return redirect(str(self.success_url))
