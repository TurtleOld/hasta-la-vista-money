"""HTML views for transaction category management."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from hasta_la_vista_money.transactions.forms import CategoryForm
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.users.services.cache import (
    invalidate_user_detailed_statistics_cache,
)


def _category_type(value: str | None) -> str:
    """Normalize category type coming from query string or POST data."""
    if value == TransactionType.INCOME:
        return TransactionType.INCOME
    return TransactionType.EXPENSE


def _clear_category_cache(user_id: int, category_type: str) -> None:
    for depth in range(1, 6):
        cache.delete(f'category_tree_{category_type}_{user_id}_{depth}')


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
        invalidate_user_detailed_statistics_cache(self.request.user.pk)
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

    def get_object(self, queryset: Any = None) -> Category:
        return get_object_or_404(
            Category,
            pk=self.kwargs['pk'],
            user=self.request.user,
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

    def form_valid(self, form: CategoryForm) -> HttpResponse:
        category = form.save(commit=False)
        category.user = self.request.user
        category.type = self.get_object().type
        category.save()
        _clear_category_cache(self.request.user.pk, category.type)
        invalidate_user_detailed_statistics_cache(self.request.user.pk)
        messages.success(self.request, _('Категория успешно обновлена.'))
        return redirect(self.success_url)


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
        invalidate_user_detailed_statistics_cache(self.request.user.pk)
        messages.success(self.request, _('Категория успешно удалена.'))
        return redirect(self.success_url)
