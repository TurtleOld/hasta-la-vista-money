import decimal
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError, QuerySet, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth

from hasta_la_vista_money.users.views import AuthRequest

if TYPE_CHECKING:
    from django.forms import ModelChoiceField
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DeleteView, FormView, ListView
from django.views.generic.edit import UpdateView
from django_filters.views import FilterView
from django_stubs_ext import StrOrPromise

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import (
    ProductFormSet,
    ReceiptFilter,
    ReceiptForm,
    SellerForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.services import (
    analyze_image_with_ai,
    paginator_custom_view,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class BaseView:
    """Base view class for receipts views."""

    def get_template_name(self) -> str:
        return 'receipts/receipts.html'

    def get_success_url(self) -> str | StrOrPromise | None:
        return reverse_lazy('receipts:list')


class ReceiptView(
    LoginRequiredMixin,
    SuccessMessageMixin[ReceiptForm],
    FilterView,
    BaseView,
):
    paginate_by: int = constants.PAGINATE_BY_DEFAULT
    model = Receipt
    filterset_class: type[ReceiptFilter] = ReceiptFilter
    template_name: str = 'receipts/receipts.html'
    no_permission_url: ClassVar[str] = cast('str', reverse_lazy('login'))
    request: AuthRequest

    def get_queryset(self) -> QuerySet[Receipt]:
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()
        group_id = self.request.GET.get('group_id') or 'my'
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = list(group.user_set.all())
                return receipt_repository.get_by_users_with_related(
                    users_in_group,
                )
            except Group.DoesNotExist:
                return receipt_repository.filter(pk__in=[])
        return receipt_repository.get_by_user_with_related(self.request.user)

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: object,
    ) -> dict[str, object]:
        user = get_object_or_404(
            User.objects.prefetch_related('groups'),
            username=self.request.user,
        )
        group_id = self.request.GET.get('group_id') or 'my'

        receipt_queryset: QuerySet[Receipt]
        seller_queryset: QuerySet[Seller]
        account_queryset: QuerySet[Account]

        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()
        seller_repository = container.receipts.seller_repository()
        account_repository = container.finance_account.account_repository()

        if group_id and group_id != 'my':
            try:
                users_in_group = list(User.objects.filter(groups__id=group_id))
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
            except Group.DoesNotExist:
                receipt_queryset = receipt_repository.filter(pk__in=[])
                seller_queryset = seller_repository.filter(pk__in=[])
                account_queryset = account_repository.filter(pk__in=[])
        else:
            receipt_queryset = receipt_repository.get_by_user_with_related(
                self.request.user,
            )
            seller_queryset = seller_repository.unique_by_name_for_user(user)
            account_queryset = account_repository.get_by_user_with_related(user)

        seller_form = SellerForm()
        receipt_filter = ReceiptFilter(
            self.request.GET,
            queryset=receipt_queryset,
            user=self.request.user,
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

        total_sum_receipts: dict[str, Any] = receipt_filter.qs.aggregate(
            total=Sum('total_sum'),
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

        page_receipts: Any = paginator_custom_view(
            self.request,
            total_receipts,
            self.paginate_by,
            'receipts',
        )

        pages_receipt_table: Any = paginator_custom_view(
            self.request,
            receipt_info_by_month,
            self.paginate_by,
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

        return context


class SellerCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[SellerForm],
    CreateView[Seller, SellerForm],
    BaseView,
):
    model = Seller
    form_class: type[SellerForm] = SellerForm

    def post(
        self,
        request: HttpRequest,
    ) -> JsonResponse:
        seller_form = SellerForm(request.POST)
        if seller_form.is_valid():
            seller = seller_form.save(commit=False)
            if not isinstance(request.user, User):
                raise TypeError('User must be authenticated')
            seller.user = request.user
            seller.save()
            messages.success(
                self.request,
                constants.SUCCESS_MESSAGE_CREATE_SELLER,
            )
            response_data: dict[str, Any] = {'success': True}
        else:
            response_data = {
                'success': False,
                'errors': seller_form.errors,
            }
        return JsonResponse(response_data)


class ReceiptCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[ReceiptForm],
    CreateView[Receipt, ReceiptForm],
    BaseView,
):
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_CREATE_RECEIPT

    def setup(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().setup(request, *args, **kwargs)
        self.request = request

    def get_form(
        self,
        form_class: type[ReceiptForm] | None = None,
    ) -> ReceiptForm:
        form = super().get_form(form_class)
        if self.request is None:
            raise ValueError('Request is not set')
        if not isinstance(self.request.user, User):
            raise TypeError('User must be authenticated')
        current_user = self.request.user
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
        request: HttpRequest,
        receipt_form: ReceiptForm,
    ) -> QuerySet[Receipt]:
        number_receipt = receipt_form.cleaned_data.get('number_receipt')
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        container = getattr(request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()
        return receipt_repository.get_by_user_and_number(
            user=request.user,
            number_receipt=number_receipt,
        )

    @staticmethod
    def create_receipt(
        request: HttpRequest,
        receipt_form: ReceiptForm,
        product_formset: 'ProductFormSet',  # type: ignore[valid-type]
        seller: Seller,
    ) -> Receipt | None:
        container = getattr(request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_creator_service = container.receipts.receipt_creator_service()
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
        number_receipt = self.check_exist_receipt(
            self.request,
            receipt_form,
        )
        if number_receipt:
            messages.error(
                self.request,
                _(constants.RECEIPT_ALREADY_EXISTS),
            )
            return False
        self.create_receipt(
            self.request,
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

    def form_valid(self, form: ReceiptForm) -> HttpResponse:
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
    LoginRequiredMixin,
    SuccessMessageMixin[ReceiptForm],
    UpdateView[Receipt, ReceiptForm],
    BaseView,
):
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm
    template_name: str = 'receipts/receipt_update.html'
    success_message: str = str(constants.SUCCESS_MESSAGE_UPDATE_RECEIPT)

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        try:
            if not isinstance(self.request.user, User):
                raise TypeError('User must be authenticated')
            container = getattr(self.request, 'container', None)
            if container is None:
                container = ApplicationContainer()
            receipt_repository = container.receipts.receipt_repository()
            receipt = receipt_repository.get_by_id(self.kwargs['pk'])
            if receipt.user != self.request.user:
                raise Http404('Receipt not found')
            return receipt
        except Receipt.DoesNotExist:
            logger.exception('Receipt not found', pk=self.kwargs['pk'])
            raise

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        receipt_form = self.get_form()

        current_user = cast('User', self.request.user)
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        account_repository = container.finance_account.account_repository()
        seller_repository = container.receipts.seller_repository()
        account_field = cast(
            'ModelChoiceField[Account]',
            receipt_form.fields['account'],
        )
        account_field.queryset = account_repository.get_by_user_with_related(
            current_user,
        )
        seller_field = cast(
            'ModelChoiceField[Seller]',
            receipt_form.fields['seller'],
        )
        seller_field.queryset = seller_repository.get_by_user(current_user)

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
        if not isinstance(self.request.user, User):
            raise TypeError('User must be authenticated')
        current_user = self.request.user
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        account_repository = container.finance_account.account_repository()
        seller_repository = container.receipts.seller_repository()
        account_field = cast(
            'ModelChoiceField[Account]',
            form.fields['account'],
        )
        account_field.queryset = account_repository.get_by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField[Seller]', form.fields['seller'])
        seller_field.queryset = seller_repository.get_by_user(current_user)
        return form

    def form_valid(self, form: ReceiptForm) -> HttpResponse:
        receipt = self.get_object()
        product_formset = ProductFormSet(self.request.POST)

        current_user = cast('User', self.request.user)
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        account_repository = container.finance_account.account_repository()
        seller_repository = container.receipts.seller_repository()
        account_field = cast(
            'ModelChoiceField[Account]',
            form.fields['account'],
        )
        account_field.queryset = account_repository.get_by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField[Seller]', form.fields['seller'])
        seller_field.queryset = seller_repository.get_by_user(current_user)

        if form.is_valid() and product_formset.is_valid():
            container = getattr(self.request, 'container', None)
            if container is None:
                container = ApplicationContainer()
            receipt_updater_service = (
                container.receipts.receipt_updater_service()
            )
            receipt_updater_service.update_receipt(
                user=cast('User', self.request.user),
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
                'Пожалуйста, исправьте ошибки в форме.',
            )
        if not product_formset.is_valid():
            messages.error(
                self.request,
                'Пожалуйста, исправьте ошибки в товарах.',
            )

        return self.render_to_response(context)

    def update_account_balance(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """
        Обновляет баланс счёта при изменении суммы чека.

        Логика:
        1. Если счёт не изменился:
           - Вычисляем разницу между старой и новой суммой
           - Если сумма увеличилась → уменьшаем баланс на разницу
           - Если сумма уменьшилась → увеличиваем баланс на разницу
        2. Если счёт изменился:
           - Возвращаем старую сумму на старый счёт
           - Списываем новую сумму с нового счёта
        """

        # Примечание: проверку владельца счёта опускаем, так как доступ к чеку
        # и валидные queryset'ы аккаунтов уже ограничивают пользователя выше.

        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        account_repository = container.finance_account.account_repository()
        try:
            old_account_obj = account_repository.get_by_id(old_account.pk)
            new_account_obj = account_repository.get_by_id(new_account.pk)

            if old_account.pk == new_account.pk:
                difference = new_total_sum - old_total_sum
                if difference > 0:
                    old_account_obj.balance -= difference
                else:
                    old_account_obj.balance += abs(difference)
                old_account_obj.save()
            else:
                old_account_obj.balance += old_total_sum
                old_account_obj.save()

                new_account_obj.balance -= new_total_sum
                new_account_obj.save()

        except Account.DoesNotExist:
            logger.exception(
                'Account not found during receipt update',
                error=str(self.request.user),
            )


class ReceiptDeleteView(
    LoginRequiredMixin,
    DeleteView[Receipt, Any],
    BaseView,
):
    model = Receipt
    success_url = reverse_lazy('receipts:list')

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        if not isinstance(self.request.user, User):
            raise TypeError('User must be authenticated')
        return get_object_or_404(
            Receipt.objects.filter(user=self.request.user)
            .select_related(
                'account',
                'seller',
            )
            .prefetch_related('product'),
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get_success_url(self) -> str:
        return str(self.success_url)

    def post(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> HttpResponse:
        receipt = self.get_object()
        account = receipt.account
        amount = receipt.total_sum
        account_balance = get_object_or_404(Account, pk=account.pk)

        try:
            if account_balance.user == self.request.user:
                account_balance.balance += amount
                account_balance.save()

                for product in receipt.product.all():
                    product.delete()

                receipt.delete()
                messages.success(
                    self.request,
                    constants.SUCCESS_MESSAGE_DELETE_RECEIPT,
                )
                return redirect(self.success_url)
        except ProtectedError:
            messages.error(
                self.request,
                constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT,
            )
            return redirect(self.success_url)
        return redirect(self.success_url)


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

        current_user = cast('User', self.request.user)

        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()

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


class UploadImageView(LoginRequiredMixin, FormView[UploadImageForm]):
    template_name = 'receipts/upload_image.html'
    form_class: type[UploadImageForm] = UploadImageForm
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))  # type: ignore[misc]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form: UploadImageForm) -> HttpResponse:
        try:
            uploaded_file = self._get_uploaded_file()
            user = cast('User', self.request.user)
            account = form.cleaned_data.get('account')
            if account is None:
                messages.error(self.request, constants.INVALID_FILE_FORMAT)
                return super().form_invalid(form)

            container = getattr(self.request, 'container', None)
            if container is None:
                container = ApplicationContainer()
            receipt_import_service = container.receipts.receipt_import_service()
            result = receipt_import_service.process_uploaded_image(
                user=user,
                account=account,
                uploaded_file=uploaded_file,
                analyze_func=analyze_image_with_ai,
            )

            if not result.success:
                if result.error == 'invalid_file':
                    messages.error(self.request, constants.INVALID_FILE_FORMAT)
                elif result.error == 'exists':
                    messages.error(
                        self.request,
                        gettext_lazy(constants.RECEIPT_ALREADY_EXISTS),
                    )
                else:
                    messages.error(
                        self.request,
                        constants.ERROR_PROCESSING_RECEIPT,
                    )
                return super().form_invalid(form)

            messages.success(
                self.request,
                'Чек успешно загружен и обработан!',
            )
            return super().form_valid(form)
        except ValueError as e:
            logger.exception('Error processing receipt', error=e)
            messages.error(
                self.request,
                constants.INVALID_FILE_FORMAT,
            )
            return super().form_invalid(form)
        except Exception as e:
            logger.exception('Error processing receipt', error=e)
            messages.error(
                self.request,
                constants.ERROR_PROCESSING_RECEIPT,
            )
            return super().form_invalid(form)

    def _get_uploaded_file(self) -> Any:
        """Extract uploaded file from request."""
        uploaded_file: Any = self.request.FILES['file']
        if isinstance(uploaded_file, list):
            uploaded_file = uploaded_file[0]
        return uploaded_file

    def _process_uploaded_file(self, uploaded_file: Any) -> dict[str, Any]:
        """Process uploaded file and return decoded JSON receipt."""
        json_receipt: Any = analyze_image_with_ai(uploaded_file)
        if json_receipt and 'json' in json_receipt:
            json_receipt = self.clean_json_response(json_receipt)
        result: dict[str, Any] = json.loads(json_receipt)
        return result

    def _handle_receipt_processing(
        self,
        decode_json_receipt: dict[str, Any],
        user: User,
        account: Account,
    ) -> HttpResponse:
        """Handle receipt processing logic."""
        number_receipt = decode_json_receipt['number_receipt']
        receipt_exists = self.check_exist_receipt(user, number_receipt)

        if receipt_exists.exists():
            messages.error(
                self.request,
                gettext_lazy(constants.RECEIPT_ALREADY_EXISTS),
            )
            return super().form_invalid(self.get_form())

        seller = self._create_or_update_seller(decode_json_receipt, user)
        products = self._create_products(decode_json_receipt, user)
        receipt = self._create_receipt(
            decode_json_receipt,
            user,
            account,
            seller,
        )

        if products:
            receipt.product.set(products)

        self._update_account_balance(
            account,
            decode_json_receipt['total_sum'],
        )

        messages.success(
            self.request,
            'Чек успешно загружен и обработан!',
        )
        return super().form_valid(self.get_form())

    def _create_or_update_seller(
        self,
        decode_json_receipt: dict[str, Any],
        user: User,
    ) -> Seller:
        """Create or update seller from receipt data."""
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        seller_repository = container.receipts.seller_repository()
        return seller_repository.update_or_create_seller(
            user=user,
            name_seller=decode_json_receipt.get('name_seller', ''),
            defaults={
                'retail_place_address': decode_json_receipt.get(
                    'retail_place_address',
                    'Нет данных',
                ),
                'retail_place': decode_json_receipt.get(
                    'retail_place',
                    'Нет данных',
                ),
            },
        )

    def _create_products(
        self,
        decode_json_receipt: dict[str, Any],
        user: User,
    ) -> list[Product]:
        """Create products from receipt data."""
        products_data = [
            Product(
                user=user,
                product_name=item['product_name'],
                category=item['category'],
                price=item['price'],
                quantity=item['quantity'],
                amount=item['amount'],
            )
            for item in decode_json_receipt.get('items', [])
        ]
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        product_repository = container.receipts.product_repository()
        return product_repository.bulk_create_products(products_data)

    def _create_receipt(
        self,
        decode_json_receipt: dict[str, Any],
        user: User,
        account: Account,
        seller: Seller,
    ) -> Receipt:
        """Create receipt from processed data."""
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()
        return receipt_repository.create_receipt(
            user=user,
            account=account,
            number_receipt=decode_json_receipt['number_receipt'],
            receipt_date=self._parse_receipt_date(
                decode_json_receipt['receipt_date'],
            ),
            nds10=decode_json_receipt.get('nds10', 0),
            nds20=decode_json_receipt.get('nds20', 0),
            operation_type=decode_json_receipt.get('operation_type', 0),
            total_sum=decode_json_receipt['total_sum'],
            seller=seller,
        )

    def _update_account_balance(
        self,
        account: Account,
        total_sum: Decimal,
    ) -> None:
        """Update account balance after receipt creation."""
        account_balance = get_object_or_404(Account, pk=account.pk)
        account_balance.balance -= decimal.Decimal(total_sum)
        account_balance.save()

    def check_exist_receipt(
        self,
        user: User,
        number_receipt: int | None,
    ) -> QuerySet[Receipt]:
        container = getattr(self.request, 'container', None)
        if container is None:
            container = ApplicationContainer()
        receipt_repository = container.receipts.receipt_repository()
        return receipt_repository.get_by_user_and_number(
            user=user,
            number_receipt=number_receipt,
        )

    @staticmethod
    def clean_json_response(text: str) -> str:
        match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    @staticmethod
    def _parse_receipt_date(date_str: str) -> datetime:
        """Parse receipt date string into timezone-aware datetime."""
        normalized_date = UploadImageView.normalize_date(date_str)
        day, month, year = normalized_date.split(' ')[0].split('.')
        hour, minute = normalized_date.split(' ')[1].split(':')
        return timezone.make_aware(
            datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                tzinfo=timezone.get_current_timezone(),
            ),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def normalize_date(date_str: str) -> str:
        try:
            day, month, year = date_str.split(' ')[0].split('.')
            hour, minute = date_str.split(' ')[1].split(':')
            aware_dt = timezone.make_aware(
                datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    tzinfo=timezone.get_current_timezone(),
                ),
                timezone.get_current_timezone(),
            )
            return aware_dt.strftime('%d.%m.%Y %H:%M')
        except ValueError:
            day, month, year_short, time = date_str.replace(' ', '.').split('.')
            current_century = str(timezone.now().year)[:2]
            return f'{day}.{month}.{current_century}{year_short} {time}'


@require_GET
def ajax_receipts_by_group(request: HttpRequest) -> HttpResponse:
    container = getattr(request, 'container', None)
    if container is None:
        container = ApplicationContainer()
    receipt_repository = container.receipts.receipt_repository()
    group_id = request.GET.get('group_id') or 'my'
    if not isinstance(request.user, User):
        receipt_queryset = receipt_repository.filter(pk__in=[])
        user_groups = Group.objects.none()
    else:
        user = User.objects.prefetch_related('groups').get(
            pk=request.user.pk,
        )
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = list(group.user_set.all())
                receipt_queryset = receipt_repository.get_by_users(
                    users_in_group,
                )
            except Group.DoesNotExist:
                receipt_queryset = receipt_repository.filter(pk__in=[])
        else:
            receipt_queryset = receipt_repository.get_by_user(user)
        user_groups = user.groups.all()

    receipts = (
        receipt_queryset.select_related('seller', 'user')
        .prefetch_related('product')
        .order_by('-receipt_date')[: constants.RECENT_RECEIPTS_LIMIT]
    )
    return render(
        request,
        'receipts/receipts_block.html',
        {
            'receipts': receipts,
            'user_groups': user_groups,
        },
    )
