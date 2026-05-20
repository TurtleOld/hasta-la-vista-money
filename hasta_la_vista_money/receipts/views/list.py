from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, QuerySet, Sum, Window
from django.db.models.expressions import F
from django.db.models.functions import RowNumber, TruncMonth

if TYPE_CHECKING:
    from django.forms import ModelChoiceField

    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.finance_account.models import Account
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import (
    ListView,
)

from hasta_la_vista_money import constants
from hasta_la_vista_money.core.mixins import EntityListViewMixin
from hasta_la_vista_money.core.views import (
    BaseEntityFilterView,
)
from hasta_la_vista_money.receipts.forms import (
    ProductFormSet,
    ReceiptFilter,
    ReceiptForm,
    SellerForm,
)
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.services import paginator_custom_view
from hasta_la_vista_money.receipts.views.base import BaseView
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


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
