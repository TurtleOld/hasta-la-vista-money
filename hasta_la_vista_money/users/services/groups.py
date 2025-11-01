from typing import cast

from django.contrib import messages
from django.contrib.auth.models import Group
from django.forms import ModelForm
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from typing_extensions import TypedDict

from hasta_la_vista_money.users.models import User


class GroupDict(TypedDict):
    """Словарь с информацией о группе."""

    id: int
    name: str


def get_user_groups(user: User) -> list[GroupDict]:
    return cast(
        'list[GroupDict]',
        list(
            user.groups.all().prefetch_related('user_set').values('id', 'name'),
        ),
    )


def get_groups_not_for_user(user: User) -> list[GroupDict]:
    return cast(
        'list[GroupDict]',
        list(
            Group.objects.exclude(
                id__in=user.groups.values_list('id', flat=True),
            )
            .prefetch_related('user_set')
            .values('id', 'name'),
        ),
    )


def create_group(form: ModelForm[Group]) -> Group:
    return form.save()


def delete_group(form: ModelForm[Group]) -> None:
    group = form.cleaned_data['group']
    group.delete()


def add_user_to_group(request: HttpRequest, user: User, group: Group) -> None:
    """
    Service to add a user to a group with checks and user messages.
    """
    if group in user.groups.all():
        messages.error(
            request,
            _('Пользователь уже состоит в выбранной группе.'),
        )
        return
    user.groups.add(group)
    messages.success(request, _('Пользователь успешно добавлен в группу.'))


def remove_user_from_group(
    request: HttpRequest,
    user: User,
    group: Group,
) -> None:
    """
    Service to remove a user from a group with checks and user messages.
    """
    if group not in user.groups.all():
        messages.error(
            request,
            _('Пользователь не состоит в выбранной группе.'),
        )
        return
    user.groups.remove(group)
    messages.success(request, _('Пользователь успешно удалён из группы.'))
