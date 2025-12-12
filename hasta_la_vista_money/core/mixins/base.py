"""Common mixins for views across the application."""

from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.db.models import QuerySet, Sum
from django.forms import BaseForm
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise
from rest_framework.request import Request as DRFRequest

from hasta_la_vista_money.services.views import get_cached_category_tree
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from django_filters import FilterSet

    from hasta_la_vista_money.core.types import RequestWithContainer


class EntityListViewMixin:
    """Mixin for common operations in entity lists (Expense, Income, Receipt).

    Provides common methods for:
    - Getting current user
    - Working with filters
    - Calculating totals
    - Working with categories
    """

    request: HttpRequest

    def get_current_user(self) -> User:
        """Get current user from request.

        Returns:
            User: Current authenticated user.

        Raises:
            Http404: If user is not found.
        """
        return get_object_or_404(User, username=self.request.user)

    def get_request_with_container(self) -> 'RequestWithContainer':
        """Get request with dependency injection container.

        Returns:
            RequestWithContainer: Request with container.
        """
        return cast('RequestWithContainer', self.request)

    def get_filtered_queryset(
        self,
        filterset_class: type['FilterSet'],
        base_queryset: QuerySet[Any],
    ) -> 'FilterSet':
        """Create and apply filter to queryset.

        Args:
            filterset_class: Filter class.
            base_queryset: Base queryset for filtering.

        Returns:
            FilterSet: Applied filter.
        """
        request = self.get_request_with_container()
        return filterset_class(
            self.request.GET,
            queryset=base_queryset,
            user=request.user,
        )

    def calculate_total_amount(
        self,
        queryset: QuerySet[Any],
        amount_field: str = 'amount',
    ) -> dict[str, Any]:
        """Calculate total amount from queryset.

        Args:
            queryset: QuerySet for calculating sum.
            amount_field: Name of the amount field.

        Returns:
            dict: Dictionary with 'total' key and sum value.
        """
        return queryset.aggregate(total=Sum(amount_field))

    def get_total_amount_value(
        self,
        queryset: QuerySet[Any],
        amount_field: str = 'amount',
    ) -> float:
        """Get total amount value from queryset.

        Args:
            queryset: QuerySet for calculating sum.
            amount_field: Name of the amount field.

        Returns:
            float: Total amount or 0 if None.
        """
        result = self.calculate_total_amount(queryset, amount_field)
        return float(result.get('total') or 0)

    def get_flattened_categories(
        self,
        categories: list[dict[str, Any]] | QuerySet[Any],
        category_type: str,
        depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Get flattened category tree with caching.

        Args:
            categories: List or QuerySet of categories.
            category_type: Type of categories ('expense' or 'income').
            depth: Depth of category tree.

        Returns:
            list: List of categories as a tree.
        """
        user = self.get_current_user()
        categories_list = (
            [dict(cat) for cat in categories]
            if hasattr(categories, 'values')
            else categories
        )
        return get_cached_category_tree(
            user_id=user.pk,
            category_type=category_type,
            categories=categories_list,
            depth=depth,
        )


class UserAuthMixin:
    """Mixin for automatic user type checking.

    Automatically checks that request.user is an instance of User,
    and raises TypeError if not. This eliminates the need to repeat
    isinstance(request.user, User) check in every view method.
    """

    def dispatch(
        self,
        request: HttpRequest | DRFRequest,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Override dispatch to check user type.

        Args:
            request: HTTP request.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            HttpResponse or Response: View response.

        Raises:
            TypeError: If request.user is not an instance of User.
        """
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_authenticated_user(self) -> User:
        """Get authenticated user with type checking.

        Returns:
            User: Authenticated user.

        Raises:
            TypeError: If request.user is not an instance of User.
        """
        request = self.request
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        return request.user


class FormErrorHandlingMixin:
    """Mixin for form error handling.

    Provides common methods for handling errors when working with forms,
    eliminating code duplication for exception handling.
    """

    def handle_form_error_with_message(
        self,
        form: BaseForm,
        error: Exception,
        error_message_template: StrOrPromise,
        **kwargs: Any,
    ) -> HttpResponse:
        """Handle form error with message via messages framework.

        Args:
            form: Form with error.
            error: Exception that occurred.
            error_message_template: Error message template.
            **kwargs: Additional keyword arguments for formatting.

        Returns:
            HttpResponse: Response with invalid form.
        """
        error_message = error_message_template.format(
            error=str(error),
            **kwargs,
        )
        request = self.request
        if isinstance(request, HttpRequest):
            messages.error(request, _(error_message))
        return cast(
            'HttpResponse',
            self.form_invalid(form),  # type: ignore[attr-defined]
        )

    def handle_form_error_with_field_error(
        self,
        form: BaseForm,
        error: Exception,
        field: str | None = None,
    ) -> HttpResponse:
        """Handle form error by adding it to form field.

        Args:
            form: Form with error.
            error: Exception that occurred.
            field: Field name for error (None for general form error).

        Returns:
            HttpResponse: Response with invalid form.
        """
        form.add_error(field, str(error))
        return cast(
            'HttpResponse',
            self.form_invalid(form),  # type: ignore[attr-defined]
        )

    def handle_ajax_error(
        self,
        error: Exception,
        status_code: int = 500,
    ) -> JsonResponse:
        """Handle error for AJAX request.

        Args:
            error: Exception that occurred.
            status_code: HTTP status code for response.

        Returns:
            JsonResponse: JSON response with error.
        """
        return JsonResponse({'error': str(error)}, status=status_code)

    def handle_ajax_error_with_success_flag(
        self,
        error: Exception,
    ) -> JsonResponse:
        """Handle error for AJAX request with success flag.

        Args:
            error: Exception that occurred.

        Returns:
            JsonResponse: JSON response with success=False flag and error.
        """
        return JsonResponse({'success': False, 'error': str(error)})

    def handle_service_error(
        self,
        form: BaseForm,
        error: Exception,
        error_message_template: str | None = None,
        use_field_error: bool = False,
    ) -> HttpResponse:
        """Handle service error when working with form.

        Universal method for handling ValueError, TypeError, PermissionDenied.

        Args:
            form: Form with error.
            error: Exception (ValueError, TypeError, PermissionDenied).
            error_message_template: Error message template.
            use_field_error: If True, use form.add_error.

        Returns:
            HttpResponse: Response with invalid form.
        """
        if use_field_error:
            return self.handle_form_error_with_field_error(form, error)
        if error_message_template:
            return self.handle_form_error_with_message(
                form,
                error,
                error_message_template,
            )
        return self.handle_form_error_with_field_error(form, error)
