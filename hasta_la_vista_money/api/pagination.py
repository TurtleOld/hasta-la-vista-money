"""Pagination classes for DRF API views."""

from rest_framework.pagination import PageNumberPagination

from hasta_la_vista_money import constants


class StandardResultsSetPagination(PageNumberPagination):
    """Стандартная пагинация для API endpoints.

    Использует настраиваемый размер страницы с возможностью
    изменения через query параметр.
    """

    page_size = constants.PAGINATE_BY_DEFAULT
    page_size_query_param = 'page_size'
    max_page_size = 100
