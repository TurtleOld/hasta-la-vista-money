import decimal
import json
import re
from collections.abc import Sequence
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

if TYPE_CHECKING:
    from django.forms import ModelChoiceField
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DeleteView, FormView, ListView
from django.views.generic.edit import UpdateView
from django_filters.views import FilterView

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
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreatorService,
)
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportService,
)
from hasta_la_vista_money.receipts.services.receipt_updater import (
    ReceiptUpdaterService,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class BaseView:
    template_name: ClassVar[str | Sequence[str] | None] = (
        'receipts/receipts.html'
    )
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))


class ReceiptView(
    LoginRequiredMixin,
    SuccessMessageMixin,  # type: ignore[type-arg]
    BaseView,
    FilterView[Receipt, ReceiptFilter],  # type: ignore[misc]
):
    paginate_by: int = constants.PAGINATE_BY_DEFAULT
    model = Receipt
    filterset_class = ReceiptFilter
    no_permission_url: ClassVar[str] = cast('str', reverse_lazy('login'))

    def get_queryset(self) -> QuerySet[Receipt]:
        group_id = self.request.GET.get('group_id') or 'my'
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                return Receipt.objects.for_users(users_in_group).with_related()
            except Group.DoesNotExist:
                return Receipt.objects.none()
        return Receipt.objects.for_user(self.request.user).with_related()

    def get_context_data(self, **kwargs: object) -> dict[str, Any]:
        user = get_object_or_404(User, username=self.request.user)
        group_id = self.request.GET.get('group_id') or 'my'

        receipt_queryset: QuerySet[Receipt]
        seller_queryset: QuerySet[Seller]
        account_queryset: QuerySet[Account]

        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                receipt_queryset = Receipt.objects.for_users(
                    users_in_group,
                ).with_related()
                seller_queryset = Seller.objects.unique_by_name_for_users(
                    users_in_group,
                )
                account_queryset = (
                    Account.objects.filter(user__in=users_in_group)
                    .select_related('user')
                    .distinct()
                )
            except Group.DoesNotExist:
                receipt_queryset = Receipt.objects.for_users([]).with_related()
                seller_queryset = Seller.objects.for_users([])
                account_queryset = Account.objects.none()
        else:
            receipt_queryset = Receipt.objects.for_user(
                self.request.user,
            ).with_related()
            seller_queryset = Seller.objects.unique_by_name_for_user(user)
            account_queryset = Account.objects.by_user_with_related(user)

        seller_form = SellerForm()  # type: ignore[no-untyped-call]
        receipt_filter = ReceiptFilter(  # type: ignore[no-untyped-call]
            self.request.GET,
            queryset=receipt_queryset,
            user=self.request.user,
        )
        receipt_form = ReceiptForm()
        account_field = cast('ModelChoiceField[Account]', receipt_form.fields['account'])
        account_field.queryset = account_queryset
        seller_field = cast('ModelChoiceField[Seller]', receipt_form.fields['seller'])
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

        context: dict[str, Any] = super().get_context_data(**kwargs)
        context['receipts'] = page_receipts
        context['receipt_filter'] = receipt_filter
        context['total_receipts'] = total_receipts
        context['total_sum_receipts'] = total_sum_receipts
        context['seller_form'] = seller_form
        context['receipt_form'] = receipt_form
        context['product_formset'] = product_formset
        context['receipt_info_by_month'] = pages_receipt_table
        context['user_groups'] = self.request.user.groups.all()

        return context


class SellerCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[SellerForm],
    BaseView,
    CreateView[Seller, SellerForm],
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
    BaseView,
    CreateView[Receipt, ReceiptForm],
):
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_CREATE_RECEIPT

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.request: HttpRequest | None = None
        super().__init__(*args, **kwargs)

    def get_form(
        self,
        form_class: type[ReceiptForm] | None = None,
    ) -> ReceiptForm:
        form = super().get_form(form_class)
        current_user = cast('User', self.request.user)
        account_field = cast('ModelChoiceField', form.fields['account'])
        account_field.queryset = Account.objects.by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField', form.fields['seller'])
        seller_field.queryset = Seller.objects.for_user(current_user)
        return form

    @staticmethod
    def check_exist_receipt(
        request: HttpRequest,
        receipt_form: ReceiptForm,
    ) -> QuerySet[Receipt]:
        number_receipt = receipt_form.cleaned_data.get('number_receipt')
        return Receipt.objects.filter(
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
        return ReceiptCreatorService.create_manual_receipt(
            user=cast('User', request.user),
            receipt_form=receipt_form,
            product_formset=product_formset,
            seller=seller,
        )

    def form_valid_receipt(
        self,
        receipt_form: ReceiptForm,
        product_formset: 'ProductFormSet',  # type: ignore[valid-type]
        seller: Seller,
    ) -> bool:
        number_receipt = self.check_exist_receipt(
            cast('HttpRequest', self.request),
            receipt_form,
        )
        if number_receipt:
            messages.error(
                cast('HttpRequest', self.request),
                _(constants.RECEIPT_ALREADY_EXISTS),
            )
            return False
        self.create_receipt(
            cast('HttpRequest', self.request),
            receipt_form,
            product_formset,
            seller,
        )
        messages.success(
            cast('HttpRequest', self.request),
            constants.SUCCESS_MESSAGE_CREATE_RECEIPT,
        )
        return True

    def setup(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.request = request
        super().setup(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        context['receipt_form'] = self.get_form()
        context['product_formset'] = ProductFormSet()
        return context

    def form_valid(self, form: ReceiptForm) -> HttpResponse:
        seller = cast('Seller', form.cleaned_data.get('seller'))
        product_formset = ProductFormSet(cast('HttpRequest', self.request).POST)

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
        product_formset = ProductFormSet(cast('HttpRequest', self.request).POST)
        context: dict[str, Any] = self.get_context_data(form=form)
        context['product_formset'] = product_formset
        return self.render_to_response(context)


class ReceiptUpdateView(
    LoginRequiredMixin,
    SuccessMessageMixin[ReceiptForm],
    UpdateView[Receipt, ReceiptForm],
):
    template_name = 'receipts/receipt_update.html'
    success_url: ClassVar[str] = cast('str', reverse_lazy('receipts:list'))
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_UPDATE_RECEIPT

    def post(
        self,
        request: HttpRequest,
        *args: object,
        **kwargs: object,
    ) -> HttpResponse:
        return super().post(request, *args, **kwargs)

    def get_object(self, queryset: QuerySet[Receipt] | None = None) -> Receipt:
        try:
            return get_object_or_404(
                Receipt.objects.select_related(
                    'user',
                    'account',
                    'seller',
                ).prefetch_related('product'),
                pk=self.kwargs['pk'],
                user=self.request.user,
            )
        except Receipt.DoesNotExist:
            logger.exception('Receipt not found', pk=self.kwargs['pk'])
            raise

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)
        receipt_form = self.get_form()

        current_user = cast('User', self.request.user)
        account_field = cast('ModelChoiceField[Account]', receipt_form.fields['account'])
        account_field.queryset = Account.objects.by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField[Seller]', receipt_form.fields['seller'])
        seller_field.queryset = Seller.objects.for_user(current_user)

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
        current_user = cast('User', self.request.user)
        account_field = cast('ModelChoiceField', form.fields['account'])
        account_field.queryset = Account.objects.by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField', form.fields['seller'])
        seller_field.queryset = Seller.objects.for_user(current_user)
        return form

    def form_valid(self, form: ReceiptForm) -> HttpResponse:
        receipt = self.get_object()
        product_formset = ProductFormSet(self.request.POST)

        current_user = cast('User', self.request.user)
        account_field = cast('ModelChoiceField[Account]', form.fields['account'])
        account_field.queryset = Account.objects.by_user_with_related(
            current_user,
        )
        seller_field = cast('ModelChoiceField[Seller]', form.fields['seller'])
        seller_field.queryset = Seller.objects.for_user(current_user)

        if form.is_valid() and product_formset.is_valid():
            ReceiptUpdaterService.update_receipt(
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

        try:
            old_account_obj = Account.objects.get(id=old_account.id)
            new_account_obj = Account.objects.get(id=new_account.id)

            if old_account.id == new_account.id:
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


class ReceiptDeleteView(LoginRequiredMixin, BaseView, DeleteView[Receipt, ReceiptForm]):  # type: ignore[misc]
    model = Receipt
    form_class: type[ReceiptForm] = ReceiptForm

    def form_valid(self, form: ReceiptForm) -> HttpResponse:
        receipt = self.get_object()
        account = receipt.account
        amount = receipt.total_sum
        account_balance = get_object_or_404(Account, id=account.id)

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


class ProductByMonthView(LoginRequiredMixin, ListView[Receipt]):
    template_name = 'receipts/purchased_products.html'
    model = Receipt
    login_url = '/login/'

    def get_context_data(
        self,
        *,
        object_list: QuerySet[Receipt] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )

        current_user = cast('User', self.request.user)

        all_purchased_products = (
            Receipt.objects.filter(user=current_user)
            .select_related('user')
            .prefetch_related('product')
            .values('product__product_name')
            .annotate(products=Count('product__product_name'))
            .order_by('-products')
            .distinct()[: constants.RECEIPTS_DISTINCT_LIMIT]
        )

        purchased_products_by_month = (
            Receipt.objects.filter(user=current_user)
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

            result = ReceiptImportService.process_uploaded_image(
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
        return json.loads(json_receipt)

    def _handle_receipt_processing(
        self, decode_json_receipt: dict[str, Any], user: User, account: Account
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
        self, decode_json_receipt: dict[str, Any], user: User
    ) -> Seller:
        """Create or update seller from receipt data."""
        return Seller.objects.update_or_create(
            user=user,
            name_seller=decode_json_receipt.get('name_seller'),
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
        )[0]

    def _create_products(
        self, decode_json_receipt: dict[str, Any], user: User
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
        return Product.objects.bulk_create(products_data)

    def _create_receipt(
        self,
        decode_json_receipt: dict[str, Any],
        user: User,
        account: Account,
        seller: Seller,
    ) -> Receipt:
        """Create receipt from processed data."""
        return Receipt.objects.create(
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

    def _update_account_balance(self, account: Account, total_sum: Decimal) -> None:
        """Update account balance after receipt creation."""
        account_balance = get_object_or_404(Account, id=account.id)
        account_balance.balance -= decimal.Decimal(total_sum)
        account_balance.save()

    @staticmethod
    def check_exist_receipt(
        user: User,
        number_receipt: int | None,
    ) -> QuerySet[Receipt]:
        return Receipt.objects.filter(
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
    group_id = request.GET.get('group_id') or 'my'
    user = request.user
    if group_id and group_id != 'my':
        try:
            group = Group.objects.get(pk=group_id)
            users_in_group = group.user_set.all()
            receipt_queryset = Receipt.objects.filter(user__in=users_in_group)
        except Group.DoesNotExist:
            receipt_queryset = Receipt.objects.none()
    else:
        receipt_queryset = Receipt.objects.filter(user=cast('User', user))

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
            'user_groups': user.groups.all(),
        },
    )
