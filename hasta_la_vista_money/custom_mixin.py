from collections.abc import Generator
from typing import Any

from django.contrib import messages
from django.db.models import ProtectedError, QuerySet
from django.shortcuts import redirect
from django.urls import reverse_lazy


class DeleteObjectMixin:
    """Mixin for handling object deletion with custom error handling."""

    success_message = ''
    error_message = ''

    def form_valid(self, form):
        """Override form_valid to handle ProtectedError."""
        try:
            obj = self.get_object()
            obj.delete()
            messages.success(
                self.request,
                self.success_message,
            )
            return super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                self.error_message,
            )
            return redirect(self.get_success_url())


class CustomSuccessURLUserMixin:
    def __init__(self):
        """Конструктов класса инициализирующий аргумент kwargs."""
        self.kwargs = None

    def get_success_url(self):
        user = self.kwargs['pk']
        return reverse_lazy('users:profile', kwargs={'pk': user})


class UpdateViewMixin:
    depth_limit = 3

    def __init__(self):
        """Конструктов класса инициализирующий аргументы класса."""
        self.template_name = None
        self.request = None

    def get_update_form(
        self,
        form_class=None,
        form_name=None,
        user=None,
        depth=None,
    ):
        model = self.get_object()
        form = form_class(instance=model, user=user, depth=depth)
        return {form_name: form}


def get_category_choices(
    queryset: QuerySet[Any],
    parent=None,
    level: int = 0,
    max_level: int = 2,
) -> Generator[tuple[Any, str], None, None]:
    """Формируем выбор категории в форме."""
    for category in queryset.filter(parent_category=parent):
        yield (category.pk, f'{"  >" * level} {category.name}')
        if level < max_level - 1:
            yield from get_category_choices(
                queryset,
                parent=category,
                level=level + 1,
                max_level=max_level,
            )


class CategoryChoicesMixin:
    field: str

    def __init__(self, *args, category_queryset=None, depth=None, **kwargs):
        """Инициализирует choices для древовидных категорий.

        Args:
            category_queryset: QuerySet категорий или None.
            depth: Глубина иерархии категорий.
        """
        super().__init__(*args, **kwargs)
        queryset_to_use = category_queryset or (
            self.fields.get(self.field).queryset
            if self.field in self.fields
            else None
        )
        if queryset_to_use is not None:
            if self.field in self.fields:
                self.fields[self.field].queryset = queryset_to_use
            category_choices = list(
                get_category_choices(
                    queryset=queryset_to_use,
                    max_level=depth or 2,
                ),
            )
            category_choices.insert(0, ('', '----------'))
            self.fields[self.field].choices = category_choices


class CategoryChoicesConfigurerMixin:
    def configure_category_choices(self, category_choices):
        """Устанавливает choices для поля категории.

        Args:
            category_choices: Последовательность пар (value, label).
        """
        self.fields[self.field].choices = category_choices


class FormQuerysetsMixin:
    """Инициализация queryset'ов полей формы из kwargs.

    Поддерживает параметры 'category_queryset' и 'account_queryset'.
    Имя поля категории берётся из атрибута 'field' формы, либо из
    'category_field_name', либо по умолчанию 'category'.
    Имя поля счёта задаётся атрибутом 'account_field_name'
    (по умолчанию 'account').
    """

    category_field_name = None
    account_field_name = 'account'

    def __init__(self, *args, **kwargs):
        category_queryset = kwargs.pop('category_queryset', None)
        account_queryset = kwargs.pop('account_queryset', None)
        super().__init__(*args, **kwargs)

        category_field = (
            getattr(self, 'field', None)
            or getattr(self, 'category_field_name', None)
            or 'category'
        )

        if category_queryset is not None and category_field in self.fields:
            self.fields[category_field].queryset = category_queryset

        account_field = getattr(self, 'account_field_name', 'account')
        if account_queryset is not None and account_field in self.fields:
            self.fields[account_field].queryset = account_queryset
