import secrets
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.models import Group
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from typing_extensions import TypedDict

from hasta_la_vista_money.constants import FAMILY_INVITE_TTL
from hasta_la_vista_money.users.models import (
    FamilyGroupMembership,
    FamilyInvite,
    User,
)


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
        list(member_groups(user).values('id', 'name')),
    )


def member_groups(user: User) -> QuerySet[Group]:
    """Return groups where user has a membership."""

    return Group.objects.filter(family_memberships__user=user).order_by('name')


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


def delete_group(form: ModelForm[Group]) -> None:
    """Delete a group.

    Args:
        form: Validated group form with 'group' in cleaned_data.
    """
    form.cleaned_data['group'].delete()


def owned_group_ids(user: User) -> QuerySet[FamilyGroupMembership, int]:
    """Return IDs of the groups where user is an owner."""

    return FamilyGroupMembership.objects.filter(
        user=user,
        role=FamilyGroupMembership.Role.OWNER,
    ).values_list('group_id', flat=True)


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
    if not FamilyGroupMembership.objects.filter(
        group=group,
        user=user,
    ).exists():
        messages.error(
            request,
            _('Пользователь не состоит в выбранной группе.'),
        )
        return
    owner_ids = set(
        FamilyGroupMembership.objects.filter(
            group=group,
            role=FamilyGroupMembership.Role.OWNER,
        ).values_list('user_id', flat=True),
    )
    if owner_ids == {user.pk}:
        messages.error(
            request,
            _('Нельзя удалить последнего владельца группы.'),
        )
        return
    user.groups.remove(group)
    FamilyGroupMembership.objects.filter(group=group, user=user).delete()
    rotate_family_invites(group)
    messages.success(request, _('Пользователь успешно удалён из группы.'))


def user_can_manage_group(user: User, group: Group) -> bool:
    """Return whether user is an owner of the family group."""

    return FamilyGroupMembership.objects.filter(
        group=group,
        user=user,
        role=FamilyGroupMembership.Role.OWNER,
    ).exists()


def readable_users(user: User, group_id: str | None = None) -> list[User]:
    """Return users whose data ``user`` may read for the selected scope.

    ``my``/empty is the user alone, ``<id>`` is every member of that group
    (empty if ``user`` is not a member), ``family`` is the union of all groups
    of ``user``. Membership comes only from ``FamilyGroupMembership``.
    """

    if not group_id or group_id == 'my':
        return [user]
    memberships = FamilyGroupMembership.objects.filter(user=user)
    if group_id != 'family':
        if not group_id.isdigit():
            return []
        memberships = memberships.filter(group_id=int(group_id))
    members = User.objects.filter(
        family_memberships__group_id__in=memberships.values('group_id'),
    )
    users = list(members.distinct().order_by('username'))
    return users or ([user] if group_id == 'family' else [])


def can_write(user: User, obj: Any) -> bool:
    """Return whether user may change the record: only its owner may."""

    return bool(obj.user_id == user.pk)


def get_family_groups(
    user: User,
    request: HttpRequest,
) -> list[FamilyGroupDict]:
    """Return groups available in family UX with optional invite links."""

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


def get_or_create_family_invite(
    group: Group,
    created_by: User,
    role: str = FamilyGroupMembership.Role.VIEWER,
) -> FamilyInvite:
    """Create or reuse a non-expired active invite link for a group owner."""

    invite = FamilyInvite.objects.filter(
        group=group,
        created_by=created_by,
        role=role,
        is_active=True,
        expires_at__gt=timezone.now(),
    ).first()
    if invite:
        return invite
    return FamilyInvite.objects.create(
        group=group,
        created_by=created_by,
        role=role,
        token=secrets.token_urlsafe(32),
        expires_at=timezone.now() + FAMILY_INVITE_TTL,
    )


def get_active_family_invite(token: str) -> FamilyInvite | None:
    """Return an active, non-expired invite for the given token."""

    return (
        FamilyInvite.objects.filter(
            token=token,
            is_active=True,
            expires_at__gt=timezone.now(),
        )
        .select_related('group', 'created_by')
        .first()
    )


def rotate_family_invites(group: Group) -> None:
    """Deactivate the active invite links of a group.

    The next ``get_or_create_family_invite`` request issues a fresh token, so
    that members removed from the group cannot reuse an old share link.
    """

    FamilyInvite.objects.filter(group=group, is_active=True).update(
        is_active=False,
    )


def accept_family_invite(user: User, token: str) -> Group | None:
    """Accept a family invite and return joined group if token is valid."""

    invite = get_active_family_invite(token)
    if invite is None:
        return None
    user.groups.add(invite.group)
    FamilyGroupMembership.objects.get_or_create(
        group=invite.group,
        user=user,
        defaults={'role': invite.role},
    )
    return invite.group
