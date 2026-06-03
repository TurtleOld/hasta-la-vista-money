"""HTML views for transaction category management."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from hasta_la_vista_money.services.views import get_cached_category_tree
from hasta_la_vista_money.transactions.forms import CategoryForm
from hasta_la_vista_money.transactions.models import Category, TransactionType


def _category_type(value: str | None) -> str:
    """Normalize category type coming from query string or POST data."""
    if value == TransactionType.INCOME:
        return TransactionType.INCOME
    return TransactionType.EXPENSE


def _clear_category_cache(user_id: int, category_type: str) -> None:
    for depth in range(1, 6):
        cache.delete(f'category_tree_{category_type}_{user_id}_{depth}')


def _find_category_node(
    categories: list[dict[str, Any]],
    category_id: int,
    *,
    level: int = 0,
) -> tuple[dict[str, Any], int] | None:
    for category in categories:
        if category['id'] == category_id:
            return category, level
        children = category.get('children') or []
        found = _find_category_node(children, category_id, level=level + 1)
        if found is not None:
            return found
    return None


class CategoryListView(LoginRequiredMixin, ListView[Category]):
    """Redirect category listing to the combined finance category page."""

    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        return redirect('finances_categories')


class CategoryCreateView(
    LoginRequiredMixin,
    CreateView[Category, CategoryForm],
):
    """Create an income or expense category for the current user."""

    model = Category
    form_class = CategoryForm
    template_name = 'transactions/category_form.html'
    success_url = reverse_lazy('finances_categories')

    def get_category_type(self) -> str:
        return _category_type(
            self.request.POST.get('type') or self.request.GET.get('type'),
        )

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial['type'] = self.get_category_type()
        return initial

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['category_queryset'] = Category.objects.filter(
            user=self.request.user,
            type=self.get_category_type(),
        )
        return kwargs

    def form_valid(self, form: CategoryForm) -> HttpResponse:
        category = form.save(commit=False)
        category.user = self.request.user
        category.type = self.get_category_type()
        category.save()
        _clear_category_cache(self.request.user.pk, category.type)
        messages.success(self.request, _('Категория успешно добавлена.'))
        return redirect(self.success_url)


class CategoryUpdateView(
    LoginRequiredMixin,
    UpdateView[Category, CategoryForm],
):
    """Update a transaction category owned by the current user."""

    model = Category
    form_class = CategoryForm
    template_name = 'transactions/category_form.html'
    success_url = reverse_lazy('finances_categories')

    def is_inline_request(self) -> bool:
        return (
            self.request.headers.get('HX-Request') == 'true'
            and self.request.GET.get('inline') == '1'
        ) or (
            self.request.headers.get('HX-Request') == 'true'
            and self.request.POST.get('inline') == '1'
        )

    def get_object(self, queryset: Any = None) -> Category:
        return get_object_or_404(
            Category,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if not self.is_inline_request():
            return super().get(request, *args, **kwargs)
        self.object = self.get_object()
        return self._render_inline_form(
            form=self.get_form(),
            status=200,
        )

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        category = self.get_object()
        kwargs['category_queryset'] = Category.objects.filter(
            user=self.request.user,
            type=category.type,
        ).exclude(pk=category.pk)
        kwargs.setdefault('initial', {})['type'] = category.type
        return kwargs

    def _inline_item_context(self, category: Category) -> dict[str, Any]:
        tree = get_cached_category_tree(
            user_id=self.request.user.pk,
            category_type=category.type,
            categories=list(
                Category.objects.filter(
                    user=self.request.user,
                    type=category.type,
                )
                .values(
                    'id',
                    'name',
                    'parent_category',
                    'parent_category__name',
                )
                .order_by('parent_category_id'),
            ),
            depth=3,
        )
        found = _find_category_node(tree, category.pk)
        if found is None:
            node = {
                'id': category.pk,
                'name': category.name,
                'parent_category': category.parent_category_id,
                'parent_category__name': (
                    category.parent_category.name
                    if category.parent_category is not None
                    else ''
                ),
                'total_children_count': category.subcategories.count(),
                'children': [],
            }
            level = 0
        else:
            node, level = found
        return {
            'category': node,
            'category_type': category.type,
            'level': level,
        }

    def _render_inline_form(
        self,
        *,
        form: CategoryForm,
        status: int,
    ) -> HttpResponse:
        category = self.get_object()
        name_attrs = form.fields['name'].widget.attrs
        name_attrs.update(
            {
                'class': 'finance-category-inline-input',
                'autocomplete': 'off',
            },
        )
        context = self._inline_item_context(category)
        context['form'] = form
        return render(
            self.request,
            'transactions/partials/_category_tree_item_form.html',
            context=context,
            status=status,
        )

    def _render_inline_item(self, *, category: Category) -> HttpResponse:
        return render(
            self.request,
            'finance_account/partials/_category_tree_item.html',
            context=self._inline_item_context(category),
        )

    def form_valid(self, form: CategoryForm) -> HttpResponse:
        category = form.save(commit=False)
        category.user = self.request.user
        category.type = self.get_object().type
        category.save()
        _clear_category_cache(self.request.user.pk, category.type)
        if self.is_inline_request():
            return self._render_inline_item(category=category)
        messages.success(self.request, _('Категория успешно обновлена.'))
        return redirect(self.success_url)

    def form_invalid(self, form: CategoryForm) -> HttpResponse:
        if self.is_inline_request():
            return self._render_inline_form(form=form, status=422)
        return super().form_invalid(form)


class CategoryDeleteView(LoginRequiredMixin, DeleteView[Category, Any]):
    """Delete a transaction category owned by the current user."""

    model = Category
    success_url = reverse_lazy('finances_categories')

    def get_object(self, queryset: Any = None) -> Category:
        return get_object_or_404(
            Category,
            pk=self.kwargs['pk'],
            user=self.request.user,
        )

    def form_valid(self, form: Any) -> HttpResponse:
        category = self.get_object()
        category_type = category.type
        try:
            category.delete()
        except ProtectedError:
            messages.error(
                self.request,
                _('Категория используется и не может быть удалена.'),
            )
            return redirect(self.success_url)
        _clear_category_cache(self.request.user.pk, category_type)
        messages.success(self.request, _('Категория успешно удалена.'))
        return redirect(self.success_url)
