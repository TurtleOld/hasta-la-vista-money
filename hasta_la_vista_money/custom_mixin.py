from typing import Any, Generator, Optional

from django.contrib import messages
from django.db.models import ProtectedError, QuerySet
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import DeleteView


class DeleteObjectMixin(DeleteView):
    model = Optional[None]
    success_url = None
    success_message = ''
    error_message = ''

    def form_valid(self, form):
        try:
            category = self.get_object()
            category.delete()
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
            return redirect(self.success_url)


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
        super().__init__(*args, **kwargs)
        if category_queryset:
            category_choices = list(
                get_category_choices(
                    queryset=category_queryset,
                    max_level=depth,
                )
            )
            category_choices.insert(0, ('', '----------'))
            self.fields[self.field].choices = category_choices
