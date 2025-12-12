"""Pagination classes for DRF API views."""

from rest_framework.pagination import PageNumberPagination

from hasta_la_vista_money import constants


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for API endpoints.

    Uses configurable page size with the ability to change it
    via query parameter.
    """

    page_size = constants.PAGINATE_BY_DEFAULT
    page_size_query_param = 'page_size'
    max_page_size = 100
