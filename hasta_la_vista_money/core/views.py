"""Shared base views used across multiple apps."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import models
from django.forms import ModelForm
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django_filters.views import FilterView

from hasta_la_vista_money import constants


class BaseEntityFilterView(LoginRequiredMixin, SuccessMessageMixin, FilterView):
    """Common configuration for entity filter views."""

    paginate_by: int | None = constants.PAGINATE_BY_DEFAULT
    no_permission_url = reverse_lazy('login')


class BaseEntityCreateView[ModelType: models.Model, FormType: ModelForm](
    LoginRequiredMixin,
    SuccessMessageMixin,
    CreateView[ModelType, FormType],
):
    """Base class for creating entities.

    Provides common configuration for entity creation views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')


class BaseEntityUpdateView[ModelType: models.Model, FormType: ModelForm](
    LoginRequiredMixin,
    SuccessMessageMixin,
    UpdateView[ModelType, FormType],
):
    """Base class for updating entities.

    Provides common configuration for entity update views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')
