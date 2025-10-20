import decimal
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, cast

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError, QuerySet, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth
from django.http import JsonResponse
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
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class BaseView:
    template_name = 'receipts/receipts.html'
    success_url = reverse_lazy('receipts:list')


class ReceiptView(
    LoginRequiredMixin,
    BaseView,
    SuccessMessageMixin,
    FilterView,
):
    paginate_by = 10
    model = Receipt
    filterset_class = ReceiptFilter
    no_permission_url = reverse_lazy('login')

    def get_queryset(self):
        group_id = self.request.GET.get('group_id') or 'my'
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                return Receipt.objects.for_users(users_in_group).with_related()
            except Group.DoesNotExist:
                return Receipt.objects.none()
        return Receipt.objects.for_user(self.request.user).with_related()

    def get_context_data(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
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
                    users_in_group
                ).with_related()
                seller_queryset = Seller.objects.unique_by_name_for_users(
                    users_in_group
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
                self.request.user
            ).with_related()
            seller_queryset = Seller.objects.unique_by_name_for_user(user)
            account_queryset = Account.objects.by_user_with_related(user)

        seller_form = SellerForm()
        receipt_filter = ReceiptFilter(
            self.request.GET,
            queryset=receipt_queryset,
            user=self.request.user,
        )
        receipt_form = ReceiptForm()
        receipt_form.fields['account'].queryset = account_queryset  # type: ignore[attr-defined]
        receipt_form.fields['seller'].queryset = seller_queryset  # type: ignore[attr-defined]

        product_formset = ProductFormSet()

        total_sum_receipts: Dict[str, Any] = receipt_filter.qs.aggregate(
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

        context = super().get_context_data(**kwargs)
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


class SellerCreateView(SuccessMessageMixin, BaseView, CreateView):
    model = Seller
    form_class = SellerForm

    def post(self, request, *args, **kwargs):
        seller_form = SellerForm(request.POST)
        if seller_form.is_valid():
            seller = seller_form.save(commit=False)
            seller.user = request.user
            seller.save()
            messages.success(
                self.request,
                constants.SUCCESS_MESSAGE_CREATE_SELLER,
            )
            response_data = {'success': True}
        else:
            response_data = {
                'success': False,
                'errors': seller_form.errors,
            }
        return JsonResponse(response_data)


class ReceiptCreateView(LoginRequiredMixin, SuccessMessageMixin, BaseView, CreateView):
    model = Receipt
    form_class = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_CREATE_RECEIPT

    def __init__(self, *args, **kwargs):
        self.request = None
        super().__init__(*args, **kwargs)

    @staticmethod
    def check_exist_receipt(request, receipt_form):
        number_receipt = receipt_form.cleaned_data.get('number_receipt')
        return Receipt.objects.filter(
            user=request.user,
            number_receipt=number_receipt,
        )

    @staticmethod
    def create_receipt(request, receipt_form, product_formset, seller):
        receipt = receipt_form.save(commit=False)
        total_sum = receipt.total_sum
        account = receipt.account
        account_balance = get_object_or_404(Account, id=account.id)
        if account_balance.user == request.user:
            account_balance.balance -= total_sum
            account_balance.save()
            receipt.user = request.user
            receipt.seller = seller
            receipt.manual = True
            receipt.save()
            for product_form in product_formset:
                if product_form.cleaned_data and not product_form.cleaned_data.get(
                    'DELETE',
                    False,
                ):
                    product_data = product_form.cleaned_data
                    if (
                        product_data.get('product_name')
                        and product_data.get('price')
                        and product_data.get('quantity')
                    ):
                        product = Product.objects.create(
                            user=request.user,
                            product_name=product_data['product_name'],
                            price=product_data['price'],
                            quantity=product_data['quantity'],
                            amount=product_data['amount'],
                        )
                        receipt.product.add(product)
            return receipt

    def form_valid_receipt(self, receipt_form, product_formset, seller):
        number_receipt = self.check_exist_receipt(self.request, receipt_form)
        if number_receipt:
            messages.error(
                self.request,
                _(constants.RECEIPT_ALREADY_EXISTS),
            )
            return False
        else:
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

    def setup(self, request, *args, **kwargs):
        self.request = request
        super().setup(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['receipt_form'] = self.get_form()
        context['product_formset'] = ProductFormSet()
        return context

    def form_valid(self, form):
        seller = form.cleaned_data.get('seller')
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
            else:
                return self.form_invalid(form)
        else:
            return self.form_invalid(form)

    def form_invalid(self, form):
        product_formset = ProductFormSet(self.request.POST)
        context = self.get_context_data(form=form)
        context['product_formset'] = product_formset
        return self.render_to_response(context)


class ReceiptUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    template_name = 'receipts/receipt_update.html'
    success_url = reverse_lazy('receipts:list')
    model = Receipt
    form_class = ReceiptForm
    success_message = constants.SUCCESS_MESSAGE_UPDATE_RECEIPT

    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_object(self, queryset: Any = None) -> Receipt:
        receipt = get_object_or_404(
            Receipt.objects.select_related(
                'user',
                'account',
                'seller',
            ).prefetch_related('product'),
            pk=self.kwargs['pk'],
            user=self.request.user,
        )
        return receipt

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        receipt_form = self.get_form()

        current_user = cast(User, self.request.user)
        receipt_form.fields['account'].queryset = Account.objects.by_user_with_related(
            current_user
        )  # type: ignore[attr-defined]
        receipt_form.fields['seller'].queryset = Seller.objects.for_user(current_user)  # type: ignore[attr-defined]

        context['receipt_form'] = receipt_form

        existing_products = self.object.product.all() if self.object else []
        initial_data = []
        for product in existing_products:
            initial_data.append(
                {
                    'product_name': product.product_name,
                    'price': product.price,
                    'quantity': product.quantity,
                    'amount': product.amount,
                },
            )
        context['product_formset'] = ProductFormSet(initial=initial_data)
        return context

    def form_valid(self, form):
        receipt = self.get_object()
        product_formset = ProductFormSet(self.request.POST)

        if form.is_valid() and product_formset.is_valid():
            old_total_sum = receipt.total_sum
            old_account = receipt.account

            receipt = form.save()

            receipt.product.clear()

            new_total_sum = Decimal('0.00')
            for product_form in product_formset:
                if product_form.cleaned_data and not product_form.cleaned_data.get(
                    'DELETE',
                    False,
                ):
                    product_data = product_form.cleaned_data
                    if (
                        product_data.get('product_name')
                        and product_data.get('price')
                        and product_data.get('quantity')
                    ):
                        current_user = cast(User, self.request.user)
                        product = Product.objects.create(
                            user=current_user,
                            product_name=product_data['product_name'],
                            price=product_data['price'],
                            quantity=product_data['quantity'],
                            amount=product_data['amount'],
                        )
                        receipt.product.add(product)
                        new_total_sum += product_data['amount']

            receipt.total_sum = new_total_sum
            receipt.save()

            new_account = receipt.account

            self.update_account_balance(
                old_account,
                new_account,
                old_total_sum,
                new_total_sum,
            )

            return super().form_valid(form)
        else:
            return self.form_invalid(form)

    def form_invalid(self, form):
        product_formset = ProductFormSet(self.request.POST)
        context = self.get_context_data(form=form)
        context['product_formset'] = product_formset

        if not form.is_valid():
            messages.error(self.request, 'Пожалуйста, исправьте ошибки в форме.')
        if not product_formset.is_valid():
            messages.error(self.request, 'Пожалуйста, исправьте ошибки в товарах.')

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

        if (
            old_account.user != self.request.user
            or new_account.user != self.request.user
        ):
            return

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
            logger.error(
                f'Account not found during receipt update for user {self.request.user}',
            )


class ReceiptDeleteView(LoginRequiredMixin, BaseView, DeleteView):
    model = Receipt

    def form_valid(self, form):
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
                messages.success(self.request, 'Чек успешно удалён!')
                return redirect(self.success_url)
        except ProtectedError:
            messages.error(self.request, 'Чек не может быть удалён!')
            return redirect(self.success_url)


class ProductByMonthView(LoginRequiredMixin, ListView):
    template_name = 'receipts/purchased_products.html'
    model = Receipt
    login_url = '/login/'

    def get_context_data(
        self, *, object_list: Any = None, **kwargs: Any
    ) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)

        current_user = cast(User, self.request.user)

        all_purchased_products = (
            Receipt.objects.filter(user=current_user)
            .select_related('user')
            .prefetch_related('product')
            .values('product__product_name')
            .annotate(products=Count('product__product_name'))
            .order_by('-products')
            .distinct()[:10]
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
            .filter(rank__lte=10)
            .order_by('month', 'rank')
        )

        data: Dict[Any, Dict[str, Decimal]] = {}

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


class UploadImageView(LoginRequiredMixin, FormView):
    template_name = 'receipts/upload_image.html'
    form_class = UploadImageForm
    success_url = reverse_lazy('receipts:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            uploaded_file = self.request.FILES['file']
            if isinstance(uploaded_file, list):
                uploaded_file = uploaded_file[0]
            user = cast(User, self.request.user)
            account = form.cleaned_data.get('account')

            json_receipt = analyze_image_with_ai(uploaded_file)
            if json_receipt and 'json' in json_receipt:
                json_receipt = self.clean_json_response(json_receipt)
            decode_json_receipt = json.loads(json_receipt)

            number_receipt = decode_json_receipt['number_receipt']
            receipt_exists = self.check_exist_receipt(user, number_receipt)
            if not receipt_exists.exists():
                seller, _ = Seller.objects.update_or_create(
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
                )

                products_data = []
                for item in decode_json_receipt.get('items', []):
                    products_data.append(
                        Product(
                            user=user,
                            product_name=item['product_name'],
                            category=item['category'],
                            price=item['price'],
                            quantity=item['quantity'],
                            amount=item['amount'],
                        ),
                    )

                products = Product.objects.bulk_create(products_data)

                receipt = Receipt.objects.create(
                    user=user,
                    account=account,
                    number_receipt=decode_json_receipt['number_receipt'],
                    receipt_date=timezone.make_aware(
                        datetime.strptime(
                            self.normalize_date(decode_json_receipt['receipt_date']),
                            '%d.%m.%Y %H:%M',
                        ),
                    ),
                    nds10=decode_json_receipt.get('nds10', 0),
                    nds20=decode_json_receipt.get('nds20', 0),
                    operation_type=decode_json_receipt.get('operation_type', 0),
                    total_sum=decode_json_receipt['total_sum'],
                    seller=seller,
                )

                if products:
                    receipt.product.set(products)

                account_balance = get_object_or_404(Account, id=account.id)
                account_balance.balance -= decimal.Decimal(
                    decode_json_receipt['total_sum'],
                )
                account_balance.save()

                messages.success(self.request, 'Чек успешно загружен и обработан!')
                return super().form_valid(form)

            messages.error(self.request, gettext_lazy(constants.RECEIPT_ALREADY_EXISTS))
            return super().form_invalid(form)
        except ValueError as e:
            logger.error(e)
            messages.error(
                self.request,
                'Неверный формат файла, попробуйте загрузить ещё раз или другой файл',
            )
            return super().form_invalid(form)
        except Exception as e:
            logger.error(f'Ошибка при обработке чека: {e}')
            messages.error(
                self.request,
                'Произошла ошибка при обработке чека. Попробуйте ещё раз.',
            )
            return super().form_invalid(form)

    @staticmethod
    def check_exist_receipt(user: User, number_receipt: int | None):
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
    def normalize_date(date_str: str) -> str:
        try:
            return datetime.strptime(date_str, '%d.%m.%Y %H:%M').strftime(
                '%d.%m.%Y %H:%M',
            )
        except ValueError:
            day, month, year_short, time = date_str.replace(' ', '.').split('.')
            current_century = str(timezone.now().year)[:2]
            return f'{day}.{month}.{current_century}{year_short} {time}'


@require_GET
def ajax_receipts_by_group(request):
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
        receipt_queryset = Receipt.objects.filter(user=user)

    receipts = (
        receipt_queryset.select_related('seller', 'user')
        .prefetch_related('product')
        .order_by('-receipt_date')[:20]
    )
    return render(
        request,
        'receipts/receipts_block.html',
        {
            'receipts': receipts,
            'user_groups': user.groups.all(),
        },
    )
