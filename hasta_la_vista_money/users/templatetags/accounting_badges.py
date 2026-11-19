"""Compact accounting problem counter for navigation and dashboard."""

from typing import Any

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def accounting_problem_count(context: dict[str, Any]) -> int:
    """Return the owner's unified problem count from the shared service."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return 0
    container = getattr(request, 'container', None)
    if container is None:
        return 0
    service = container.users.accounting_problem_service()
    return int(service.summary(user).total_items)
