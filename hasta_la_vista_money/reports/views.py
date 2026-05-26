from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from hasta_la_vista_money.reports.services.aggregation import (
    budget_charts,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class ReportView(LoginRequiredMixin, SuccessMessageMixin[Any], TemplateView):
    template_name = 'reports/reports.html'
    no_permission_url = reverse_lazy('login')
    success_url = reverse_lazy('reports:list')
    period_choices = (
        ('m', _('Месяц')),
        ('q', _('Квартал')),
        ('y', _('Год')),
        ('all', _('Всё время')),
    )

    def get(self, request: HttpRequest) -> HttpResponse:
        budget_chart_data = self.prepare_budget_charts(request)
        template_name = self.template_name
        if template_name is None:
            raise ValueError('template_name must be set')
        return render(
            request,
            template_name,
            budget_chart_data,
        )

    def prepare_budget_charts(self, request: HttpRequest) -> dict[str, Any]:
        """Prepare budget chart data."""
        if isinstance(request.user, AnonymousUser):
            raise TypeError('User must be authenticated')
        selected_period = request.GET.get('period', 'y')
        allowed_periods = {choice[0] for choice in self.period_choices}
        if selected_period not in allowed_periods:
            selected_period = 'y'
        charts_data = budget_charts(
            cast('User', request.user),
            period=selected_period,
        )
        result = cast('dict[str, Any]', charts_data)
        result.update(
            {
                'selected_period': selected_period,
                'period_choices': self.period_choices,
                'finances_url': reverse('finances'),
            },
        )
        return result


class ReportsAnalyticMixin(TemplateView):
    def get_context_report(self) -> dict[str, Any]:
        return {}
