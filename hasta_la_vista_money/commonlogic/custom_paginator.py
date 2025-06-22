from typing import Any, Sequence, TypeVar, Union

from django.core.paginator import Page, Paginator
from django.db.models import QuerySet

T = TypeVar('T')


def paginator_custom_view(
    request,
    queryset: Union[QuerySet[Any], list[Any]],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[T]]:
    """
    Кастомный пагинатор для данных.

    :param request
    :param queryset: QuerySet или список данных
    :param paginate_by: количество элементов на странице
    :param page_name: имя параметра страницы в URL
    :return Page: страница с данными

    """
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
