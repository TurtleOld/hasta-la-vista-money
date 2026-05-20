import structlog
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise

logger = structlog.get_logger(__name__)
_INSUFFICIENT_FUNDS_CODE = 'insufficient_funds'


def _validation_error_message(error: ValidationError) -> str:
    """Return a readable message from Django ValidationError."""
    for validation_error in getattr(error, 'error_list', ()):
        if validation_error.code == _INSUFFICIENT_FUNDS_CODE:
            return str(_('Недостаточно средств на счете'))
    if error.messages:
        return ' '.join(str(message) for message in error.messages)
    return str(_('Ошибка проверки данных.'))


class BaseView:
    """Base view class for receipts views."""

    def get_template_name(self) -> str:
        return 'receipts/receipts.html'

    def get_success_url(self) -> str | StrOrPromise | None:
        return reverse_lazy('receipts:list')
