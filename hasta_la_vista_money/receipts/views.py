import decimal
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, FormView, ListView
from django_filters.views import FilterView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.custom_paginator import (
    paginator_custom_view,
)
from hasta_la_vista_money.commonlogic.views import collect_info_receipt
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
from hasta_la_vista_money.receipts.tasks import process_receipt_image
from hasta_la_vista_money.taskiq import broker
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

    def get_context_data(self, *args, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        if user.is_authenticated:
            seller_form = SellerForm()
            receipt_filter = ReceiptFilter(
                self.request.GET,
                queryset=Receipt.objects.all(),
                user=self.request.user,
            )
            receipt_form = ReceiptForm()
            receipt_form.fields['account'].queryset = user.finance_account_users
            receipt_form.fields['seller'].queryset = user.seller_users.distinct(
                'name_seller',
            )

            product_formset = ProductFormSet()

            total_sum_receipts = receipt_filter.qs.aggregate(
                total=Sum('total_sum'),
            )
            total_receipts = receipt_filter.qs

            receipt_info_by_month = collect_info_receipt(user=self.request.user)

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
    """Представление для загрузки и обработки изображений чеков."""

    template_name = 'receipts/modals/add_receipt.html'
    form_class = UploadImageForm
    success_url = reverse_lazy('receipts:list')

    def get_form_kwargs(self):
        """Передаем пользователя в форму."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def post(self, request, *args, **kwargs):
        """Обработка POST запроса с HTMX."""
        if request.headers.get('HX-Request'):
            return self.handle_htmx_request(request)
        return super().post(request, *args, **kwargs)

    def handle_htmx_request(self, request):
        """Обработка HTMX запроса."""
        try:
            if 'file' not in request.FILES:
                return self.render_error_response('Файл не найден')

            uploaded_file = request.FILES['file']
            if isinstance(uploaded_file, list):
                uploaded_file = uploaded_file[0]  # type: ignore[assignment]

            account_id = request.POST.get('account')
            if not account_id:
                return self.render_error_response('Счёт не выбран')

            account = get_object_or_404(Account, id=account_id, user=request.user)

            # Читаем файл в байты для асинхронной обработки
            image_data = uploaded_file.read()

            # Запускаем асинхронную задачу
            task = broker.kiq(process_receipt_image)(
                image_data=image_data,
                user_id=request.user.id,
                account_id=account.pk,
            )

            # Возвращаем ID задачи для отслеживания
            return JsonResponse(
                {
                    'success': True,
                    'task_id': task.task_id,
                    'message': 'Обработка чека началась. Вы получите уведомление по завершении.',
                },
            )

        except Exception as e:
            logger.error(f'Error in HTMX request: {str(e)}', exc_info=True)
            return self.render_error_response(f'Ошибка: {str(e)}')

    def render_success_response(self, message):
        """Рендеринг успешного ответа для HTMX"""
        from django.http import HttpResponse

        html = f"""
        <div class="alert alert-success" role="alert">
            <i class="bi bi-check-circle me-2"></i>
            {message}
        </div>
        """
        return HttpResponse(html)

    def render_error_response(self, error_message):
        """Рендеринг ответа с ошибкой для HTMX"""
        from django.http import HttpResponse

        html = f"""
        <div class="alert alert-danger" role="alert">
            <i class="bi bi-exclamation-triangle me-2"></i>
            {error_message}
        </div>
        """
        return HttpResponse(html)

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

    def form_valid(self, form):
        """Обработка обычных POST запросов (не HTMX)"""
        try:
            uploaded_file = self.request.FILES['file']
            if isinstance(uploaded_file, list):
                uploaded_file = uploaded_file[0]  # type: ignore[assignment]
            user = self.request.user  # type: ignore[assignment]
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


class TaskStatusView(LoginRequiredMixin, View):
    """Представление для проверки статуса асинхронных задач."""

    def get(self, request, task_id):
        """Получение статуса задачи."""
        try:
            # Получаем результат задачи
            result = broker.get_result(task_id)

            if result.is_ready():
                if result.is_success():
                    return JsonResponse(
                        {'status': 'completed', 'result': result.return_value},
                    )
                else:
                    return JsonResponse(
                        {'status': 'failed', 'error': str(result.return_value)},
                    )
            else:
                return JsonResponse(
                    {'status': 'pending', 'message': 'Задача выполняется...'},
                )

        except Exception as e:
            logger.error(f'Error checking task status: {str(e)}')
            return JsonResponse(
                {'status': 'error', 'error': 'Ошибка при проверке статуса задачи'},
            )
