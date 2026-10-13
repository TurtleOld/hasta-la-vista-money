from django import template

from hasta_la_vista_money.receipts.services.processing_errors import (
    REPORTABLE_ERROR_CODES,
)

register = template.Library()


@register.filter
def reports_to_issue_tracker(error_code: str) -> bool:
    return error_code in REPORTABLE_ERROR_CODES
