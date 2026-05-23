import secrets
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import Group
from django.forms import ModelForm
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from typing_extensions import TypedDict

from hasta_la_vista_money.users.models import (
    FamilyGroupMembership,
    FamilyInvite,
    User,
)

DEFAULT_FAMILY_GROUP_NAME = 'Семья'


class GroupDict(TypedDict):
    """Group information dictionary.

    Attributes:
        id: Group ID.
        name: Group name.
    """

    id: int
    name: str


class FamilyGroupDict(GroupDict):
    """Family group information with current user's role."""

    role: str
    role_label: str
    invite_url: str | None


def get_user_groups(user: User) -> list[GroupDict]:
    """Get all groups for user.

    Args:
        user: User to get groups for.

    Returns:
        List of GroupDict with user's groups.
    """
    return cast(
        'list[GroupDict]',
        list(
            user.groups.all().prefetch_related('user_set').values('id', 'name'),
        ),
    )


def get_groups_not_for_user(user: User) -> list[GroupDict]:
    """Get groups not assigned to user.

    Args:
        user: User to check groups for.

    Returns:
        List of GroupDict with groups not assigned to user.
    """
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
    """Create a new group.

    Args:
        form: Validated group form.

    Returns:
        Created Group instance.
    """
    group = form.save()
    owner = getattr(form, 'current_user', None)
    if isinstance(owner, User):
        owner.groups.add(group)
        FamilyGroupMembership.objects.update_or_create(
            group=group,
            user=owner,
            defaults={'role': FamilyGroupMembership.Role.OWNER},
        )
    return group


def get_or_create_default_family_group(user: User) -> Group:
    """Return the user's primary family group and ensure owner role exists."""

    owner_membership = (
        FamilyGroupMembership.objects.filter(
            user=user,
            role=FamilyGroupMembership.Role.OWNER,
        )
        .select_related('group')
        .first()
    )
    if owner_membership is not None:
        return owner_membership.group

    group = user.groups.filter(name=DEFAULT_FAMILY_GROUP_NAME).first()
    if group is None:
        group, _created = Group.objects.get_or_create(
            name=DEFAULT_FAMILY_GROUP_NAME,
        )
        user.groups.add(group)

    FamilyGroupMembership.objects.update_or_create(
        group=group,
        user=user,
        defaults={'role': FamilyGroupMembership.Role.OWNER},
    )
    return group


def delete_group(form: ModelForm[Group]) -> None:
    """Delete a group.

    Args:
        form: Validated group form with 'group' in cleaned_data.
    """
    group = form.cleaned_data['group']
    if group.name == DEFAULT_FAMILY_GROUP_NAME:
        return
    group.delete()


def add_user_to_group(request: HttpRequest, user: User, group: Group) -> None:
    """Add user to group with checks and user messages.

    Args:
        request: HTTP request object.
        user: User to add to group.
        group: Group to add user to.
    """
    if group in user.groups.all():
        messages.error(
            request,
            _('Пользователь уже состоит в выбранной группе.'),
        )
        return
    user.groups.add(group)
    FamilyGroupMembership.objects.update_or_create(
        group=group,
        user=user,
        defaults={'role': FamilyGroupMembership.Role.VIEWER},
    )
    messages.success(request, _('Пользователь успешно добавлен в группу.'))


def remove_user_from_group(
    request: HttpRequest,
    user: User,
    group: Group,
) -> None:
    """Remove user from group with checks and user messages.

    Args:
        request: HTTP request object.
        user: User to remove from group.
        group: Group to remove user from.
    """
    if group not in user.groups.all():
        messages.error(
            request,
            _('Пользователь не состоит в выбранной группе.'),
        )
        return
    user.groups.remove(group)
    FamilyGroupMembership.objects.filter(group=group, user=user).delete()
    messages.success(request, _('Пользователь успешно удалён из группы.'))


def user_can_manage_group(user: User, group: Group) -> bool:
    """Return whether user is an owner of the family group."""

    return FamilyGroupMembership.objects.filter(
        group=group,
        user=user,
        role=FamilyGroupMembership.Role.OWNER,
    ).exists()


def user_has_group_access(user: User, group_id: str | None) -> bool:
    """Return whether user may read data for selected group."""

    if not group_id or group_id in {'my', 'family'}:
        return True
    if not group_id.isdigit():
        return False
    return FamilyGroupMembership.objects.filter(
        user=user,
        group_id=int(group_id),
    ).exists()


def get_family_groups(
    user: User,
    request: HttpRequest,
) -> list[FamilyGroupDict]:
    """Return groups available in family UX with optional invite links."""

    get_or_create_default_family_group(user)
    groups = Group.objects.filter(
        id__in=FamilyGroupMembership.objects.filter(user=user).values_list(
            'group_id',
            flat=True,
        ),
    ).order_by('name')
    memberships = {
        membership.group_id: membership
        for membership in FamilyGroupMembership.objects.filter(
            user=user,
            group__in=groups,
        )
    }
    result: list[FamilyGroupDict] = []
    for group in groups:
        membership = memberships.get(group.pk)
        role = (
            membership.role if membership else FamilyGroupMembership.Role.VIEWER
        )
        invite_url = None
        if role == FamilyGroupMembership.Role.OWNER:
            invite = get_or_create_family_invite(group, user)
            invite_url = request.build_absolute_uri(
                reverse('users:groups:join', kwargs={'token': invite.token}),
            )
        result.append(
            {
                'id': group.pk,
                'name': group.name,
                'role': role,
                'role_label': str(FamilyGroupMembership.Role(role).label),
                'invite_url': invite_url,
            },
        )
    return result


def get_family_group_ids(user: User) -> list[int]:
    """Return group IDs that participate in family finance sharing."""

    get_or_create_default_family_group(user)
    return list(
        FamilyGroupMembership.objects.filter(user=user).values_list(
            'group_id',
            flat=True,
        ),
    )


def get_or_create_family_invite(
    group: Group,
    created_by: User,
    role: str = FamilyGroupMembership.Role.VIEWER,
) -> FamilyInvite:
    """Create or reuse an active invite link for a family group owner."""

    invite = FamilyInvite.objects.filter(
        group=group,
        created_by=created_by,
        role=role,
        is_active=True,
    ).first()
    if invite:
        return invite
    return FamilyInvite.objects.create(
        group=group,
        created_by=created_by,
        role=role,
        token=secrets.token_urlsafe(32),
    )


def accept_family_invite(user: User, token: str) -> Group | None:
    """Accept a family invite and return joined group if token is valid."""

    invite = (
        FamilyInvite.objects.filter(
            token=token,
            is_active=True,
        )
        .select_related('group')
        .first()
    )
    if invite is None:
        return None
    user.groups.add(invite.group)
    membership = FamilyGroupMembership.objects.filter(
        group=invite.group,
        user=user,
    ).first()
    if membership is None:
        FamilyGroupMembership.objects.create(
            group=invite.group,
            user=user,
            role=invite.role,
        )
    elif membership.role != FamilyGroupMembership.Role.OWNER:
        membership.role = invite.role
        membership.save(update_fields=['role', 'updated_at'])
    return invite.group
