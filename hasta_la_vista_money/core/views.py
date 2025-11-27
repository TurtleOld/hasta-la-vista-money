"""Shared base views used across multiple apps."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django_filters.views import FilterView

from hasta_la_vista_money import constants


class BaseEntityFilterView(LoginRequiredMixin, SuccessMessageMixin, FilterView):
    """Common configuration for entity filter views."""

    paginate_by: int = constants.PAGINATE_BY_DEFAULT
    no_permission_url = reverse_lazy('login')
