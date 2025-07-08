from django.db.models import Count, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from hasta_la_vista_money.users.models import User


def build_category_tree(categories, parent_id=None, depth=2, current_depth=1):
    """
    Формирование дерева категория для отображения на сайте.
    Добавляет поле total_children_count — количество всех вложенных подкатегорий.
    """

    def count_all_descendants(cat_id):
        count = 0
        children = [c for c in categories if c['parent_category'] == cat_id]
        count += len(children)
        for child in children:
            count += count_all_descendants(child['id'])
        return count

    for category in categories:
        if category['parent_category'] == parent_id:
            if current_depth < depth:
                yield {
                    'id': category['id'],
                    'name': category['name'],
                    'parent_category': category['parent_category'],
                    'parent_category__name': category['parent_category__name'],
                    'children': build_category_tree(
                        categories,
                        category['id'],
                        depth,
                        current_depth + 1,
                    ),
                    'total_children_count': count_all_descendants(category['id']),
                }
            else:
                yield {
                    'id': category['id'],
                    'name': category['name'],
                    'parent_category': category['parent_category'],
                    'parent_category__name': category['parent_category__name'],
                    'total_children_count': count_all_descendants(category['id']),
                }


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


def get_new_type_operation(model, id_type_operation, request):
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
