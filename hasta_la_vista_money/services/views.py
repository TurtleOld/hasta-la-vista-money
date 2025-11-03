from collections import defaultdict
from collections.abc import Generator
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Model, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.forms import ModelForm
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
            list,
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


def _convert_generators_to_lists(
    node: dict[str, Any],
) -> dict[str, Any]:
    """
    Рекурсивно преобразует генераторы в списки для сериализации.

    Args:
        node: Узел дерева категорий

    Returns:
        Узел с преобразованными генераторами в списки
    """
    result = dict(node)
    if 'children' in result and hasattr(result['children'], '__iter__'):
        if not isinstance(result['children'], (list, tuple)):
            result['children'] = list(result['children'])
        result['children'] = [
            _convert_generators_to_lists(child) for child in result['children']
        ]
    return result


def get_cached_category_tree(
    user_id: int,
    category_type: str,
    categories: list[dict[str, Any]] | QuerySet,
    depth: int = 2,
) -> list[dict[str, Any]]:
    """
    Получение кешированного дерева категорий.

    Args:
        user_id: ID пользователя
        category_type: Тип категорий (expense/income)
        categories: Список или QuerySet категорий
        depth: Глубина дерева

    Returns:
        Список категорий в виде дерева с подсчитанными потомками
    """
    cache_key = f'category_tree_{category_type}_{user_id}_{depth}'
    cached_tree = cache.get(cache_key)

    if cached_tree is not None:
        return cached_tree

    tree_generator = build_category_tree(categories, depth=depth)
    tree = [_convert_generators_to_lists(node) for node in tree_generator]

    cache.set(cache_key, tree, 300)

    return tree


def collect_info_receipt(user: User) -> Any:
    """
    Сбор информации о чеках для отображения на страницах сайта.

    :param user: User
    :return: QuerySet с данными о чеках
    """
    return (
        user.receipt_users.annotate(  # type: ignore[attr-defined]
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


def get_queryset_type_income_expenses(
    type_id: int | None,
    model: type[Model],
    form: ModelForm[Any],
) -> Model:
    """Функция получения queryset."""
    if type_id:
        return get_object_or_404(model, id=type_id)
    return form.save(commit=False)  # type: ignore[no-any-return]


def get_new_type_operation(
    model: type[Model],
    id_type_operation: int,
    request: HttpRequest,
) -> Model:
    """Get new type operation."""
    expense = get_object_or_404(model, pk=id_type_operation, user=request.user)
    if 'income' in request.path:
        expense.account.balance += expense.amount  # type: ignore[attr-defined]
    else:
        expense.account.balance -= expense.amount  # type: ignore[attr-defined]
    expense.account.save()  # type: ignore[attr-defined]
    return model.objects.create(  # type: ignore[no-any-return]
        user=expense.user,  # type: ignore[attr-defined]
        account=expense.account,  # type: ignore[attr-defined]
        category=expense.category,  # type: ignore[attr-defined]
        amount=expense.amount,  # type: ignore[attr-defined]
        date=expense.date,  # type: ignore[attr-defined]
    )
