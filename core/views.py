"""Base view classes for common patterns across the application.

This module provides reusable base classes for FilterView, CreateView,
and UpdateView to reduce code duplication and ensure consistent behavior
across different entities.
"""

from typing import Any, TypeVar

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Model
from django.forms import BaseModelForm
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django_filters.views import FilterView

from hasta_la_vista_money import constants

ModelType = TypeVar('ModelType', bound=Model)
FormType = TypeVar('FormType', bound=BaseModelForm[Any])


class BaseEntityFilterView(
    LoginRequiredMixin,
    SuccessMessageMixin[Any],
    FilterView,
):
    """Base class for entity list views with filtering and pagination.

    Provides common configuration for FilterView including:
    - Authentication requirement
    - Success messages
    - Default pagination
    - Permission URL
    """

    paginate_by = constants.PAGINATE_BY_DEFAULT
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for the view."""
        context: dict[str, Any] = super().get_context_data(**kwargs)
        return context


class BaseEntityCreateView[ModelType, FormType](
    LoginRequiredMixin,
    SuccessMessageMixin[Any],
    CreateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for entity creation views.

    Provides common configuration for CreateView including:
    - Authentication requirement
    - Success messages
    - Permission URL
    """

    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for the view."""
        context: dict[str, Any] = super().get_context_data(**kwargs)
        return context


class BaseEntityUpdateView[ModelType, FormType](
    LoginRequiredMixin,
    SuccessMessageMixin[Any],
    UpdateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for entity update views.

    Provides common configuration for UpdateView including:
    - Authentication requirement
    - Success messages
    - Permission URL
    """

    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Get context data for the view."""
        context: dict[str, Any] = super().get_context_data(**kwargs)
        return context
