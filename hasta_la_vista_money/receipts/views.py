import decimal
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DeleteView, FormView, ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.custom_paginator import (
    paginator_custom_view,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import (
    ProductFormSet,
    ReceiptFilter,
    ReceiptForm,
    SellerForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.services import analyze_image_with_ai
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
    """Класс представления чека на сайте."""

    paginate_by = 10
    model = Receipt
    filterset_class = ReceiptFilter
    no_permission_url = reverse_lazy('login')

    def get_queryset(self):
        group_id = self.request.GET.get('group_id')
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                return Receipt.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                return Receipt.objects.none()
        return Receipt.objects.filter(user=self.request.user)

    def get_context_data(self, *args, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        group_id = self.request.GET.get('group_id')
        if group_id and group_id != 'my':
            try:
                group = Group.objects.get(pk=group_id)
                users_in_group = group.user_set.all()
                receipt_queryset = Receipt.objects.filter(user__in=users_in_group)
                seller_queryset = Seller.objects.filter(
                    user__in=users_in_group,
                ).distinct('name_seller')
                account_queryset = Account.objects.filter(user__in=users_in_group)
            except Group.DoesNotExist:
                receipt_queryset = Receipt.objects.none()
                seller_queryset = Seller.objects.none()
                account_queryset = Account.objects.none()
        else:
            receipt_queryset = Receipt.objects.filter(user=self.request.user)
            seller_queryset = user.seller_users.distinct('name_seller')
            account_queryset = user.finance_account_users

        seller_form = SellerForm()
        receipt_filter = ReceiptFilter(
            self.request.GET,
            queryset=receipt_queryset,
            user=self.request.user,
        )
        receipt_form = ReceiptForm()
        receipt_form.fields['account'].queryset = account_queryset
        receipt_form.fields['seller'].queryset = seller_queryset

        product_formset = ProductFormSet()

        total_sum_receipts = receipt_filter.qs.aggregate(
            total=Sum('total_sum'),
        )
        total_receipts = receipt_filter.qs

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

        page_receipts = paginator_custom_view(
            self.request,
            total_receipts,
            self.paginate_by,
            'receipts',
        )

        # Paginator receipts table
        pages_receipt_table = paginator_custom_view(
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
        """
        Конструктов класса инициализирующий аргументы класса.

        :param args:
        :param kwargs:
        """
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
                product = product_form.save(commit=False)
                product.user = request.user
                product.save()
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

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)

        all_purchased_products = (
            Receipt.objects.filter(user=self.request.user)
            .values('product__product_name')
            .annotate(products=Count('product__product_name'))
            .order_by('-products')
            .distinct()[:10]
        )

        purchased_products_by_month = (
            Receipt.objects.filter(user=self.request.user)
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

        data = {}

        for item in purchased_products_by_month:
            product_name = item['product__product_name']
            month = item['month']
            total_quantity = item['total_quantity']

            if month not in data:
                data[month] = {}

            if product_name not in data[month]:
                data[month][product_name] = 0

            data[month][product_name] += total_quantity or Decimal(0)

        context['purchased_products_by_month'] = data
        context['frequently_purchased_products'] = all_purchased_products

        return context


class UploadImageView(LoginRequiredMixin, FormView):
    """Классическая синхронная обработка загрузки и обработки изображений чеков."""

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
            user = self.request.user
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
                    receipt_date=datetime.strptime(
                        self.normalize_date(decode_json_receipt['receipt_date']),
                        '%d.%m.%Y %H:%M',
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
    def check_exist_receipt(user: Any, number_receipt: Any) -> Any:
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
            current_century = str(datetime.now().year)[:2]
            return f'{day}.{month}.{current_century}{year_short} {time}'


@require_GET
def ajax_receipts_by_group(request):
    group_id = request.GET.get('group_id')
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
    receipts_data = []
    for receipt in receipts:
        products = list(receipt.product.values_list('product_name', flat=True)[:3])
        receipts_data.append(
            {
                'id': receipt.pk,
                'seller': receipt.seller.name_seller if receipt.seller else '',
                'receipt_date': receipt.receipt_date.strftime('%d.%m.%Y %H:%M'),
                'total_sum': float(receipt.total_sum),
                'operation_type': receipt.operation_type,
                'is_foreign': receipt.user != user,
                'owner': receipt.user.username,
                'products': products,
                'url': f'/receipts/{receipt.pk}/',
            },
        )
    user_groups = [{'id': group.id, 'name': group.name} for group in user.groups.all()]
    return JsonResponse(
        {
            'receipts': receipts_data,
            'user_groups': user_groups,
            'current_user_id': user.pk,
        },
    )
