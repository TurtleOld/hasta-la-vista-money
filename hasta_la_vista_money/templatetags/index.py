from typing import Any

from django import template

register = template.Library()


@register.filter
def index(sequence: Any, idx: int) -> Any:
    try:
        return sequence[idx]
    except (IndexError, TypeError):
        return ''


@register.simple_tag
def diff_by_index(list1: Any, list2: Any, idx: int) -> Any:
    try:
        return (list1[idx] or 0) - (list2[idx] or 0)
    except (IndexError, TypeError):
        return ''


@register.filter
def div(value: Any, arg: Any) -> Any:
    try:
        return (float(value) / float(arg)) * 100
    except (ValueError, ZeroDivisionError, TypeError):
        return ''
