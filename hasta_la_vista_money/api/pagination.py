"""Pagination classes for DRF API views."""

from rest_framework.pagination import PageNumberPagination

from hasta_la_vista_money import constants


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for API endpoints.

    Uses configurable page size with the ability to change it
    via query parameter.
    """

    page_size = constants.PAGINATE_BY_DEFAULT
    page_size_query_param = 'size'
    max_page_size = 100

    def get_page_size(self, request):  # type: ignore[override]
        """Support both Tabulator's `size` and legacy DRF `page_size`.

        Tabulator uses `size` by default. Other API clients may still send
        `page_size`, so we keep backwards compatibility.
        """

        if 'size' in request.query_params:
            self.page_size_query_param = 'size'
            return super().get_page_size(request)

        if 'page_size' in request.query_params:
            self.page_size_query_param = 'page_size'
            return super().get_page_size(request)

        return self.page_size
