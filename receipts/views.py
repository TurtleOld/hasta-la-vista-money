from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy
from django_filters.views import FilterView
from django_filters import rest_framework as filters

from receipts.forms import ReceiptsFilter
from receipts.models import Receipt


class ReceiptView(LoginRequiredMixin, SuccessMessageMixin, FilterView):
    model = Receipt
    template_name = 'receipts/receipts.html'
    context_object_name = 'receipts'
    ordering = ['-receipt_date']
    filterset_class = ReceiptsFilter
    filter_backends = (filters.DjangoFilterBackend,)

    error_message = gettext_lazy('У вас нет прав на просмотр данной страницы! '
                                 'Авторизуйтесь!')
    no_permission_url = 'login'

    def handle_no_permission(self):
        messages.error(self.request, self.error_message)
        return redirect(self.no_permission_url)
