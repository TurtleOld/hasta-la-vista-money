from django import template

register = template.Library()


@register.filter
def startswith(value, arg):
    """Check if a string starts with a given prefix."""
    return str(value).startswith(arg)
