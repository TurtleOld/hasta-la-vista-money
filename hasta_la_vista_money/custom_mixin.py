from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Protocol, cast

from django.contrib import messages
from django.db.models import Model, ProtectedError, QuerySet
from django.shortcuts import redirect
from django.urls import reverse_lazy

if TYPE_CHECKING:
    from django.forms import BaseForm, ModelForm
    from django.http import HttpRequest, HttpResponse


def get_category_choices(
    queryset: QuerySet[Any],
    parent: Model | None = None,
    level: int = 0,
    max_level: int = 2,
) -> Generator[tuple[Any, str], None, None]:
    """Generate category choices for form.

    Creates hierarchical category choices with indentation to show
    parent-child relationships.

    Args:
        queryset: QuerySet of category models.
        parent: Parent category (None for root level).
        level: Current nesting level.
        max_level: Maximum nesting depth.

    Yields:
        Tuples of (category_id, formatted_name) with indentation.
    """
    for category in queryset.filter(parent_category=parent):
        yield (category.pk, f'{"  >" * level} {category.name}')
        if level < max_level - 1:
            yield from get_category_choices(
                queryset,
                parent=category,
                level=level + 1,
                max_level=max_level,
            )


class DeleteObjectMixin:
    """Mixin for handling object deletion with custom error handling."""

    success_message: str = ''
    error_message: str = ''

    def form_valid(self, form: 'BaseForm') -> 'HttpResponse':
        """Override form_valid to handle ProtectedError."""
        try:
            obj = self.get_object()  # type: ignore[attr-defined]
            obj.delete()
            messages.success(
                self.request,  # type: ignore[attr-defined]
                self.success_message,
            )
            return super().form_valid(form)  # type: ignore[misc,no-any-return]
        except ProtectedError:
            messages.error(
                self.request,  # type: ignore[attr-defined]
                self.error_message,
            )
            url = self.get_success_url()  # type: ignore[attr-defined]
            return redirect(url)


class CustomSuccessURLUserMixin:
    def __init__(self) -> None:
        """Initialize class with kwargs argument."""
        self.kwargs: dict[str, Any] | None = None

    def get_success_url(self) -> str:
        """Get success URL with user pk from kwargs."""
        if self.kwargs is None:
            msg = 'kwargs must be set before calling get_success_url'
            raise ValueError(msg)
        user = self.kwargs['pk']
        return str(reverse_lazy('users:profile', kwargs={'pk': user}))


class FormWithExtraArgs(Protocol):
    """Protocol for forms that accept extra arguments."""

    def __init__(
        self,
        instance: Any | None = None,
        user: Any = None,
        depth: int | None = None,
        **kwargs: Any,
    ) -> None: ...


class UpdateViewMixin:
    depth_limit: int = 3

    def __init__(self) -> None:
        """Initialize class with class arguments."""
        self.template_name: str | None = None
        self.request: HttpRequest | None = None

    def get_update_form(
        self,
        form_class: type[FormWithExtraArgs] | None = None,
        form_name: str | None = None,
        user: Any = None,
        depth: int | None = None,
    ) -> dict[str, 'ModelForm[Any]']:
        """Get update form for the view."""
        if form_class is None:
            msg = 'form_class must be provided'
            raise ValueError(msg)
        if form_name is None:
            msg = 'form_name must be provided'
            raise ValueError(msg)
        model = self.get_object()  # type: ignore[attr-defined]
        form = form_class(instance=model, user=user, depth=depth)
        return {form_name: form}  # type: ignore[dict-item]


class FormWithFields(Protocol):
    """Protocol for forms with fields attribute."""

    fields: dict[str, Any]


class CategoryChoicesMixin:
    field: str

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[Any] | None = None,
        depth: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize choices for hierarchical categories.

        Args:
            category_queryset: QuerySet of categories or None.
            depth: Category hierarchy depth.
        """
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'fields'):
            return

        form_self = cast('FormWithFields', self)
        field_obj = form_self.fields.get(self.field)
        queryset_to_use = category_queryset or (
            field_obj.queryset
            if field_obj is not None and self.field in form_self.fields
            else None
        )
        if queryset_to_use is not None:
            if self.field in form_self.fields:
                form_self.fields[self.field].queryset = queryset_to_use
            category_choices = list(
                get_category_choices(
                    queryset=queryset_to_use,
                    max_level=depth or 2,
                ),
            )
            category_choices.insert(0, ('', '----------'))
            form_self.fields[self.field].choices = category_choices


class CategoryChoicesConfigurerMixin:
    field: str

    def configure_category_choices(
        self,
        category_choices: list[tuple[Any, str]],
    ) -> None:
        """Set choices for category field.

        Args:
            category_choices: Sequence of (value, label) pairs.
        """
        if not hasattr(self, 'fields'):
            return
        form_self = cast('FormWithFields', self)
        if self.field in form_self.fields:
            form_self.fields[self.field].choices = category_choices


class FormQuerysetsMixin:
    """Initialize form field querysets from kwargs.

    Supports 'category_queryset' and 'account_queryset' parameters.
    Category field name is taken from form's 'field' attribute, or
    from 'category_field_name', or defaults to 'category'.
    Account field name is set by 'account_field_name' attribute
    (defaults to 'account').
    """

    category_field_name: str | None = None
    account_field_name: str = 'account'

    def __init__(
        self,
        *args: Any,
        category_queryset: QuerySet[Any] | None = None,
        account_queryset: QuerySet[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if 'category_queryset' in kwargs:
            category_queryset = kwargs.pop('category_queryset')
        if 'account_queryset' in kwargs:
            account_queryset = kwargs.pop('account_queryset')
        super().__init__(*args, **kwargs)

        category_field = (
            getattr(self, 'field', None)
            or getattr(self, 'category_field_name', None)
            or 'category'
        )

        if not hasattr(self, 'fields'):
            return

        form_self = cast('FormWithFields', self)
        if category_queryset is not None and category_field in form_self.fields:
            form_self.fields[category_field].queryset = category_queryset

        account_field = getattr(self, 'account_field_name', 'account')
        if account_queryset is not None and account_field in form_self.fields:
            form_self.fields[account_field].queryset = account_queryset
