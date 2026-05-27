from collections.abc import Sequence
from typing import Any

from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest


def paginator_custom_view(
    request: HttpRequest,
    queryset: QuerySet[Any] | list[Any],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[Any]]:
    """Paginate queryset or list with a custom page parameter name."""
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
