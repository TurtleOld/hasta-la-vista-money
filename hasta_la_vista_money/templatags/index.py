from django import template

register = template.Library()


@register.filter
def index(sequence, idx):
    try:
        return sequence[idx]
    except (IndexError, TypeError):
        return ""


@register.simple_tag
def diff_by_index(list1, list2, idx):
    try:
        return (list1[idx] or 0) - (list2[idx] or 0)
    except Exception:
        return ""


@register.filter
def div(value, arg):
    try:
        return (float(value) / float(arg)) * 100
    except (ValueError, ZeroDivisionError, TypeError):
        return ""
