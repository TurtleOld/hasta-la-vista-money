from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership
from hasta_la_vista_money.users.services.groups import (
    GroupDict,
    create_group,
    delete_group,
    get_family_groups,
    get_groups_not_for_user,
    get_or_create_family_invite,
    get_user_groups,
    user_has_group_access,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


def _dummy_get_response(_request: HttpRequest) -> HttpResponse:
    return HttpResponse()


class GroupsServiceTest(TestCase):
    """Tests for user group services."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user
        self.group: Group = Group.objects.create(name='TestGroup')

    def test_get_user_groups_and_not_for_user(self) -> None:
        self.user.groups.add(self.group)
        user_groups: list[GroupDict] = get_user_groups(self.user)
        self.assertTrue(any(g['name'] == 'TestGroup' for g in user_groups))
        not_for_user: list[GroupDict] = get_groups_not_for_user(self.user)
        self.assertFalse(any(g['name'] == 'TestGroup' for g in not_for_user))

    def test_create_and_delete_group(self) -> None:
        form: GroupCreateForm = GroupCreateForm(data={'name': 'NewGroup'})
        form.current_user = self.user
        self.assertTrue(form.is_valid())
        group: Group = create_group(form)
        self.assertTrue(Group.objects.filter(name='NewGroup').exists())
        self.assertIn(group, self.user.groups.all())
        self.assertTrue(
            FamilyGroupMembership.objects.filter(
                group=group,
                user=self.user,
                role=FamilyGroupMembership.Role.OWNER,
            ).exists(),
        )
        delete_form: GroupDeleteForm = GroupDeleteForm(data={'group': group.pk})
        self.assertTrue(delete_form.is_valid())
        delete_form.cleaned_data = {'group': group}
        delete_group(delete_form)  # type: ignore[arg-type]
        self.assertFalse(Group.objects.filter(name='NewGroup').exists())

    def test_add_and_remove_user_to_group(self) -> None:
        factory: RequestFactory = RequestFactory()
        request: HttpRequest = factory.get('/')
        SessionMiddleware(_dummy_get_response).process_request(request)
        request.session.save()
        MessageMiddleware(_dummy_get_response).process_request(request)

        add_form: AddUserToGroupForm = AddUserToGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk},
        )
        self.assertTrue(add_form.is_valid())
        add_form.save(request)
        self.assertIn(self.group, self.user.groups.all())
        self.assertTrue(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.user,
                role=FamilyGroupMembership.Role.VIEWER,
            ).exists(),
        )

        remove_form: DeleteUserFromGroupForm = DeleteUserFromGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk},
        )
        self.assertTrue(remove_form.is_valid())
        remove_form.save(request)
        self.assertNotIn(self.group, self.user.groups.all())
        self.assertFalse(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.user,
            ).exists(),
        )

    def test_family_invite_and_access_helpers(self) -> None:
        factory: RequestFactory = RequestFactory()
        request: HttpRequest = factory.get('/')
        self.user.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )

        invite = get_or_create_family_invite(self.group, self.user)
        second_invite = get_or_create_family_invite(self.group, self.user)

        self.assertEqual(invite.pk, second_invite.pk)
        self.assertTrue(user_has_group_access(self.user, str(self.group.pk)))
        self.assertFalse(user_has_group_access(self.user, '999999'))

        family_groups = get_family_groups(self.user, request)
        self.assertEqual(
            family_groups[0]['role'],
            FamilyGroupMembership.Role.OWNER,
        )
        self.assertIn(invite.token, family_groups[0]['invite_url'] or '')
