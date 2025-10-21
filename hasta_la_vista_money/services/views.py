from collections import defaultdict
from collections.abc import Generator
from typing import Any

from django.db.models import Count, Model, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.users.models import User


class CategoryTreeBuilder:
    """Строит дерево категорий и считает число всех потомков."""

    def __init__(
        self,
        categories: list[dict[str, Any]] | QuerySet,
        depth: int,
    ) -> None:
        self.depth = depth
        self.cats = (
            list(categories) if hasattr(categories, 'values') else categories
        )
        self.children_map: dict[int | None, list[dict[str, Any]]] = defaultdict(
            list
        )
        for c in self.cats:
            self.children_map[c['parent_category']].append(c)
        self._memo: dict[int, int] = {}

    def count_desc(self, cid: int) -> int:
        cached = self._memo.get(cid)
        if cached is not None:
            return cached
        total = 0
        for ch in self.children_map.get(cid, ()):
            total += 1 + self.count_desc(ch['id'])
        self._memo[cid] = total
        return total

    def build(
        self,
        parent_id: int | None,
        current_depth: int,
    ) -> Generator[dict[str, Any], None, None]:
        for cat in self.children_map.get(parent_id, ()):
            node = {
                'id': cat['id'],
                'name': cat['name'],
                'parent_category': cat['parent_category'],
                'parent_category__name': cat['parent_category__name'],
                'total_children_count': self.count_desc(cat['id']),
            }
            if current_depth < self.depth:
                node['children'] = self.build(cat['id'], current_depth + 1)
            yield node


def build_category_tree(
    categories: list[dict[str, Any]] | QuerySet,
    parent_id: int | None = None,
    depth: int = 2,
    current_depth: int = 1,
) -> Generator[dict[str, Any], None, None]:
    """
    Формирование дерева категорий для отображения.
    Добавляет total_children_count — число всех вложенных подкатегорий.
    """
    builder = CategoryTreeBuilder(categories=categories, depth=depth)
    yield from builder.build(parent_id=parent_id, current_depth=current_depth)


def collect_info_receipt(user: User) -> QuerySet:
    """
    Сбор информации о чеках для отображения на страницах сайта.

    :param user: User
    :return: QuerySet
    """
    return (
        user.receipt_users.annotate(
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


def get_queryset_type_income_expenses(type_id, model, form):
    """Функция получения queryset."""
    if type_id:
        return get_object_or_404(model, id=type_id)
    return form.save(commit=False)


def get_new_type_operation(
    model: type[Model],
    id_type_operation: int,
    request: HttpRequest,
) -> Model:
    """Get new type operation."""
    expense = get_object_or_404(model, pk=id_type_operation, user=request.user)
    if 'income' in request.path:
        expense.account.balance += expense.amount
    else:
        expense.account.balance -= expense.amount
    expense.account.save()
    return model.objects.create(
        user=expense.user,
        account=expense.account,
        category=expense.category,
        amount=expense.amount,
        date=expense.date,
    )
