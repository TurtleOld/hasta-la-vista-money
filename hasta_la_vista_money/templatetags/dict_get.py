from typing import Any

from django import template

register = template.Library()


@register.filter
def dict_get(d: dict[str, Any] | Any, key: str) -> Any:
    return d.get(key)
