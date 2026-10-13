from django import template

from hasta_la_vista_money import constants

register = template.Library()


@register.simple_tag
def issue_tracker_url() -> str:
    return constants.ISSUE_TRACKER_URL
