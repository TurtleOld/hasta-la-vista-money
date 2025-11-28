"""Shared base views used across multiple apps."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import models
from django.forms import BaseForm
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django_filters.views import FilterView

from hasta_la_vista_money import constants


class BaseEntityFilterView(
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    FilterView,
):
    """Common configuration for entity filter views."""

    paginate_by: int | None = constants.PAGINATE_BY_DEFAULT
    no_permission_url = reverse_lazy('login')


class BaseEntityCreateView[  # type: ignore[misc]
    ModelType: models.Model,
    FormType,
](
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    CreateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for creating entities.

    Provides common configuration for entity creation views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')


class BaseEntityUpdateView[  # type: ignore[misc]
    ModelType: models.Model,
    FormType,
](
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    UpdateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for updating entities.

    Provides common configuration for entity update views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')
