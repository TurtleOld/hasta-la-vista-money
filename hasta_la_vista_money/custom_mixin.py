from typing import Any, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import DeleteView


class CustomNoPermissionMixin(LoginRequiredMixin):
    no_permission_url: str | None = None
    permission_denied_message = ''
    redirect_field_name = ''
    request: HttpRequest

    def handle_no_permission(self) -> Any:
        messages.error(self.request, self.permission_denied_message)
        if self.no_permission_url:
            return redirect(self.no_permission_url)
        return redirect('/')


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
