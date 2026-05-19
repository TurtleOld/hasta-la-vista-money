from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, ProtectedError, QuerySet, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth

from hasta_la_vista_money.core.mixins.base import FormErrorHandlingMixin
from hasta_la_vista_money.core.types import RequestWithContainer

if TYPE_CHECKING:
    from django.forms import ModelChoiceField
from django.forms import Form
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    View,
)
from django_stubs_ext import StrOrPromise

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import EntityListViewMixin, UserAuthMixin
from hasta_la_vista_money.core.views import (
    BaseEntityCreateView,
    BaseEntityFilterView,
    BaseEntityUpdateView,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import (
    PendingReceiptProductFormSet,
    PendingReceiptReviewForm,
    ProductFormSet,
    ReceiptFilter,
    ReceiptForm,
    SellerForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.services import paginator_custom_view
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    compute_image_hash,
)
from hasta_la_vista_money.receipts.tasks import process_pending_receipt
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


def _validation_error_message(error: ValidationError) -> str:
    """Return a readable message from Django ValidationError."""
    for validation_error in getattr(error, 'error_list', ()):
        if validation_error.code == _INSUFFICIENT_FUNDS_CODE:
            return str(_('Недостаточно средств на счете'))
    if error.messages:
        return ' '.join(str(message) for message in error.messages)
    return str(_('Ошибка проверки данных.'))


class BaseView:
    """Base view class for receipts views."""

    def get_template_name(self) -> str:
        return 'receipts/receipts.html'

    def get_success_url(self) -> str | StrOrPromise | None:
        return reverse_lazy('receipts:list')


class ReceiptView(BaseEntityFilterView, BaseView, EntityListViewMixin):
    model = Receipt
    filterset_class: type[ReceiptFilter] = ReceiptFilter
    template_name: str = 'receipts/receipts.html'

    def get_queryset(self) -> QuerySet[Receipt]:
        request = self.get_request_with_container()
        receipt_repository = request.container.receipts.receipt_repository()
        group_id = request.GET.get('group_id') or 'my'
        account_service = request.container.core.account_service()
        users_in_group = account_service.get_users_for_group(
            request.user,
            group_id,
        )
        if users_in_group:
            return cast(
                'QuerySet[Receipt, Receipt]',
                receipt_repository.get_by_users_with_related(users_in_group),
            )
        return cast(
            'QuerySet[Receipt, Receipt]',
            receipt_repository.filter(pk__in=[]),
        )

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: object,
    ) -> dict[str, object]:
        request = self.get_request_with_container()
        user = get_object_or_404(
            User.objects.prefetch_related('groups'),
            username=request.user,
        )
        group_id = request.GET.get('group_id') or 'my'

        receipt_queryset: QuerySet[Receipt]
        seller_queryset: QuerySet[Seller]
        account_queryset: QuerySet[Account]

        receipt_repository = request.container.receipts.receipt_repository()
        seller_repository = request.container.receipts.seller_repository()
        account_repository = (
            request.container.finance_account.account_repository()
        )

        account_service = request.container.core.account_service()
        users_in_group = account_service.get_users_for_group(user, group_id)

        if users_in_group:
            receipt_queryset = receipt_repository.get_by_users_with_related(
                users_in_group,
            )
            seller_queryset = seller_repository.unique_by_name_for_users(
                users_in_group,
            )
            account_queryset = account_repository.get_by_user_and_group(
                user,
                group_id,
            )
        else:
            receipt_queryset = receipt_repository.filter(pk__in=[])
            seller_queryset = seller_repository.filter(pk__in=[])
            account_queryset = account_repository.filter(pk__in=[])

        seller_form = SellerForm()
        receipt_filter = self.get_filtered_queryset(
            ReceiptFilter,
            receipt_queryset,
        )
        receipt_form = ReceiptForm()
        account_field = cast(
            'ModelChoiceField[Account]',
            receipt_form.fields['account'],
        )
        account_field.queryset = account_queryset
        seller_field = cast(
            'ModelChoiceField[Seller]',
            receipt_form.fields['seller'],
        )
        seller_field.queryset = seller_queryset

        product_formset = ProductFormSet()

        total_sum_receipts = self.calculate_total_amount(
            receipt_filter.qs,
            amount_field='total_sum',
        )
        total_receipts: QuerySet[Receipt] = receipt_filter.qs

        receipt_info_by_month = (
            receipt_queryset.annotate(
                month=TruncMonth('receipt_date'),
            )
            .values(
                'month',
                'account__name_account',
            )
            .annotate(
                count=Count('id'),
                total_amount=Sum('total_sum'),
            )
            .order_by('-month')
        )

        paginate_by_value = (
            self.paginate_by if self.paginate_by is not None else 10
        )
        page_receipts: Any = paginator_custom_view(
            self.request,
            total_receipts,
            paginate_by_value,
            'receipts',
        )

        pages_receipt_table: Any = paginator_custom_view(
            self.request,
            receipt_info_by_month,
            paginate_by_value,
            'receipts',
        )

        context: dict[str, object] = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )
        context['receipts'] = page_receipts
        context['receipt_filter'] = receipt_filter
        context['total_receipts'] = total_receipts
        context['total_sum_receipts'] = total_sum_receipts
        context['seller_form'] = seller_form
        context['receipt_form'] = receipt_form
        context['product_formset'] = product_formset
        context['receipt_info_by_month'] = pages_receipt_table
        context['user_groups'] = user.groups.all()
        context['pending_receipts'] = (
            PendingReceipt.objects.filter(
                user=request.user,
                expires_at__gt=timezone.now(),
            )
            .select_related('account')
            .order_by('-created_at')
        )

        return context


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

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        receipt_form = self.get_form()
        self._setup_form_querysets(receipt_form)

        context['receipt_form'] = receipt_form

        existing_products = self.object.product.all()
        initial_data: list[dict[str, Any]] = [
            {
                'product_name': product.product_name,
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


class ProductByMonthView(LoginRequiredMixin, ListView[Receipt]):
    template_name = 'receipts/purchased_products.html'
    model = Receipt
    login_url = '/login/'

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )

        request = cast('RequestWithContainer', self.request)
        current_user = cast('User', request.user)

        receipt_repository = request.container.receipts.receipt_repository()

        all_purchased_products = (
            receipt_repository.filter(user=current_user)
            .select_related('user')
            .prefetch_related('product')
            .values('product__product_name')
            .annotate(products=Count('product__product_name'))
            .order_by('-products')
            .distinct()[: constants.RECEIPTS_DISTINCT_LIMIT]
        )

        purchased_products_by_month = (
            receipt_repository.filter(user=current_user)
            .select_related('user')
            .prefetch_related('product')
            .annotate(month=TruncMonth('receipt_date'))
            .values('month', 'product__product_name')
            .annotate(total_quantity=Sum('product__quantity'))
            .annotate(
                rank=Window(
                    expression=RowNumber(),
                    partition_by=[F('month')],
                    order_by=F('total_quantity').desc(),
                ),
            )
            .filter(rank__lte=constants.RECEIPT_RANK_LIMIT)
            .order_by('month', 'rank')
        )

        data: dict[Any, dict[str, Decimal]] = {}

        for item in purchased_products_by_month:
            product_name = item['product__product_name']
            month = item['month']
            total_quantity = item['total_quantity']

            if month not in data:
                data[month] = {}

            if product_name not in data[month]:
                data[month][product_name] = Decimal(0)

            data[month][product_name] += total_quantity or Decimal(0)

        context['purchased_products_by_month'] = data
        context['frequently_purchased_products'] = all_purchased_products

        return context


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

        uploaded_file = self._get_uploaded_file()
        image_hash = compute_image_hash(uploaded_file)

        pending_receipt_service = (
            request.container.receipts.pending_receipt_service()
        )

        duplicate = pending_receipt_service.find_duplicate(
            user=user,
            image_hash=image_hash,
        )
        if duplicate is not None:
            return self._handle_duplicate(duplicate)

        try:
            pending_receipt = pending_receipt_service.create_processing_job(
                user=user,
                account=account,
                image_file=uploaded_file,
                image_hash=image_hash,
            )
        except Exception as exc:
            logger.exception('Error queuing receipt for processing', error=exc)
            return self.handle_form_error_with_message(
                form,
                exc,
                constants.ERROR_PROCESSING_RECEIPT,
            )

        async_result = process_pending_receipt.delay(pending_receipt.pk)
        pending_receipt_service.attach_task_id(
            pending_receipt=pending_receipt,
            task_id=async_result.id,
        )

        messages.success(
            request,
            _(
                'Чек поставлен в обработку. '
                'Когда распознавание завершится, он появится в списке.',
            ),
        )
        return redirect('receipts:list')

    def _get_uploaded_file(self) -> Any:
        """Extract uploaded file from request."""
        uploaded_file: Any = self.request.FILES['file']
        if isinstance(uploaded_file, list):
            uploaded_file = uploaded_file[0]
        return uploaded_file

    def _handle_duplicate(self, duplicate: Any) -> HttpResponse:
        """Show a duplicate-upload message and redirect to receipts list."""
        if duplicate.kind == 'pending':
            messages.warning(
                self.request,
                _(
                    'Этот чек уже загружен и сейчас обрабатывается '
                    'либо ожидает проверки.',
                ),
            )
        else:
            messages.warning(
                self.request,
                _('Этот чек уже сохранён ранее.'),
            )
        return redirect('receipts:list')


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
        async_result = process_pending_receipt.delay(pending.pk)
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
