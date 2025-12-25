from collections import defaultdict
from collections.abc import Generator
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar, Union, cast

from django.core.cache import cache
from django.db.models import Count, Model, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.forms import ModelForm
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
    from hasta_la_vista_money.income.models import Income, IncomeCategory
else:
    from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
    from hasta_la_vista_money.income.models import Income, IncomeCategory

M = TypeVar('M', bound=Model)
ExpenseOrIncome = Union['Expense', 'Income']


class CategoryTreeBuilder:
    """Build category tree and count all descendants.

    Constructs hierarchical category structure with total children count
    for each category node.
    """

    def __init__(
        self,
        categories: list[dict[str, Any]] | QuerySet[Model, Model],
        depth: int,
    ) -> None:
        """Initialize CategoryTreeBuilder.

        Args:
            categories: List or QuerySet of category dictionaries.
            depth: Maximum depth for tree building.
        """
        self.depth = depth
        self.cats = (
            list(categories) if hasattr(categories, 'values') else categories
        )
        self.children_map: dict[int | None, list[dict[str, Any]]] = defaultdict(
            list,
        )
        for c in self.cats:
            if isinstance(c, dict) and 'parent_category' in c:
                parent_id: int | None = c.get('parent_category')
                self.children_map[parent_id].append(c)
        self._memo: dict[int, int] = {}

    def count_desc(self, cid: int) -> int:
        """Count all descendants for category.

        Args:
            cid: Category ID.

        Returns:
            Total number of descendants including nested children.
        """
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
        """Build category tree starting from parent.

        Args:
            parent_id: Parent category ID (None for root).
            current_depth: Current depth in tree.

        Yields:
            Category dictionaries with children and total_children_count.
        """
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
    categories: list[dict[str, Any]] | QuerySet[Model, Model],
    parent_id: int | None = None,
    depth: int = 2,
    current_depth: int = 1,
) -> Generator[dict[str, Any], None, None]:
    """Build category tree for display.

    Creates hierarchical category structure with total_children_count
    field indicating number of all nested subcategories.

    Args:
        categories: List or QuerySet of category dictionaries.
        parent_id: Parent category ID (None for root).
        depth: Maximum tree depth.
        current_depth: Current depth in tree.

    Yields:
        Category dictionaries with hierarchical structure.
    """
    builder = CategoryTreeBuilder(categories=categories, depth=depth)
    yield from builder.build(parent_id=parent_id, current_depth=current_depth)


def _convert_generators_to_lists(
    node: dict[str, Any],
) -> dict[str, Any]:
    """Recursively convert generators to lists for serialization.

    Args:
        node: Category tree node.

    Returns:
        Node with generators converted to lists.
    """
    result = dict(node)
    if 'children' in result and hasattr(result['children'], '__iter__'):
        if not isinstance(result['children'], list | tuple):
            result['children'] = list(result['children'])
        result['children'] = [
            _convert_generators_to_lists(child) for child in result['children']
        ]
    return result


def get_cached_category_tree(
    user_id: int,
    category_type: str,
    categories: list[dict[str, Any]] | QuerySet[Model, Model],
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
        return cast('list[dict[str, Any]]', cached_tree)

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


def get_queryset_type_income_expenses(
    type_id: int | None,
    model: type[M],
    form: ModelForm[M],
) -> M:
    """Get model instance by ID or from form.

    Args:
        type_id: Optional model instance ID.
        model: Model class.
        form: Validated model form.

    Returns:
        Model instance from ID or form.

    Raises:
        Http404: If type_id provided and instance not found.
        ValueError: If form save returns None.
    """
    if type_id:
        return get_object_or_404(model, id=type_id)
    instance = form.save(commit=False)
    if instance is None:
        raise ValueError('Form save returned None')
    return instance


def get_new_type_operation[M: Model](
    model: type[M],
    id_type_operation: int,
    request: HttpRequest,
) -> M:
    """Get operation instance and prepare for new operation.

    Args:
        model: Model class (Expense or Income).
        id_type_operation: Operation instance ID.
        request: HTTP request object.

    Returns:
        Model instance for new operation creation.

    Raises:
        Http404: If operation not found.
    """
    expense = cast(
        'ExpenseOrIncome',
        get_object_or_404(model, pk=id_type_operation, user=request.user),
    )
    account = expense.account
    amount = Decimal(str(expense.amount))

    if 'income' in request.path:
        account.balance = Decimal(str(account.balance)) + amount
    else:
        account.balance = Decimal(str(account.balance)) - amount
    account.save()

    if isinstance(expense, Income):
        income_category: IncomeCategory = expense.category
        return cast(
            'M',
            Income.objects.create(
                user=expense.user,
                account=expense.account,
                category=income_category,
                amount=expense.amount,
                date=expense.date,
            ),
        )
    expense_category: ExpenseCategory = expense.category
    return cast(
        'M',
        Expense.objects.create(
            user=expense.user,
            account=expense.account,
            category=expense_category,
            amount=expense.amount,
            date=expense.date,
        ),
    )
