"""Views for explicit owner confirmation of account coverage periods."""

from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from hasta_la_vista_money.finance_account.forms import AccountCoverageForm
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class AccountCoverageConfirmView(LoginRequiredMixin, View):
    """Confirm an inclusive period for an own account, without money writes."""

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        del args, kwargs
        request_with_container = cast('RequestWithContainer', request)
        user = request.user
        if not isinstance(user, User):
            return HttpResponse(status=403)
        form = AccountCoverageForm(data=request.POST, user=user)
        if not form.is_valid():
            messages.error(
                request,
                _('Не удалось подтвердить покрытие: проверьте даты и счёт'),
            )
            return HttpResponseRedirect(reverse('finance_account:list'))

        account = form.cleaned_data['account']
        source = form.cleaned_data['source']
        upload = form.cleaned_data.get('statement_upload')
        container = request_with_container.container
        finance_container = container.finance_account
        service = finance_container.account_coverage_service()
        try:
            service.confirm(
                owner=user,
                account=account,
                period_start=form.cleaned_data['period_start'],
                period_end=form.cleaned_data['period_end'],
                source=source,
                statement_upload=upload,
            )
        except Exception:
            messages.error(
                request,
                _('Не удалось подтвердить покрытие выбранного периода'),
            )
            return HttpResponseRedirect(reverse('finance_account:list'))
        messages.success(
            request,
            _('Покрытие периода подтверждено'),
        )
        return HttpResponseRedirect(reverse('finance_account:list'))
