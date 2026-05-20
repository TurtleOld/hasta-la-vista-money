from typing import Literal, TypedDict

from django.http import (
    HttpRequest,
    HttpResponseBase,
)
from django.shortcuts import redirect
from django.views.generic import TemplateView


class Transaction(TypedDict):
    id: int
    type: Literal['expense', 'income']
    date: str
    amount: str
    category: str
    account: str


class IndexView(TemplateView):
    def dispatch(
        self,
        request: HttpRequest,
    ) -> HttpResponseBase:
        if request.user.is_authenticated:
            return redirect('finance_account:list')
        return redirect('login')
