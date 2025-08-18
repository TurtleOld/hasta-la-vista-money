from django import template

register = template.Library()


@register.filter
def startswith(value: str, arg: str) -> bool:
    """Check if a string starts with a given prefix."""
    return str(value).startswith(arg)
