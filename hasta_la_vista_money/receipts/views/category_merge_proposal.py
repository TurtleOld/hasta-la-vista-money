from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View

from hasta_la_vista_money.core.mixins import UserAuthMixin
from hasta_la_vista_money.receipts.models import CategoryMergeProposal

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class CategoryMergeProposalView(
    LoginRequiredMixin,
    UserAuthMixin,
    ListView[CategoryMergeProposal],
):
    template_name = 'receipts/category_twins.html'
    context_object_name = 'proposals'

    def get_queryset(self) -> Any:
        request = cast('RequestWithContainer', self.request)
        service = request.container.receipts.category_merge_proposal_service()
        return service.list_pending(user=self.get_authenticated_user())


class CategoryMergeProposalMergeView(LoginRequiredMixin, UserAuthMixin, View):
    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        container = cast('RequestWithContainer', request).container
        service = container.receipts.category_merge_proposal_service()
        proposal_id = int(cast('int', kwargs.get('pk')))
        survivor = service.merge(
            user=self.get_authenticated_user(),
            proposal_id=proposal_id,
        )
        if survivor is None:
            messages.error(request, _('Категории объединить не удалось.'))
        else:
            messages.success(request, _('Категории объединены.'))
        return redirect('receipts:category_twins')


class CategoryMergeProposalKeepView(LoginRequiredMixin, UserAuthMixin, View):
    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        container = cast('RequestWithContainer', request).container
        service = container.receipts.category_merge_proposal_service()
        proposal_id = int(cast('int', kwargs.get('pk')))
        kept = service.keep(
            user=self.get_authenticated_user(),
            proposal_id=proposal_id,
        )
        if kept:
            messages.success(request, _('Пара оставлена без изменений.'))
        else:
            messages.error(request, _('Не удалось обработать предложение.'))
        return redirect('receipts:category_twins')
