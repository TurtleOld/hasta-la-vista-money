from typing import ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
)
from hasta_la_vista_money.users.services.groups import (
    create_group,
    delete_group,
    get_groups_not_for_user,
    get_user_groups,
)

User = get_user_model()


class GroupsServiceTest(TestCase):
    """Tests for user group services."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self):
        self.user = User.objects.first()
        self.group = Group.objects.create(name='TestGroup')

    def test_get_user_groups_and_not_for_user(self):
        self.user.groups.add(self.group)
        user_groups = get_user_groups(self.user)
        self.assertTrue(any(g['name'] == 'TestGroup' for g in user_groups))
        not_for_user = get_groups_not_for_user(self.user)
        self.assertFalse(any(g['name'] == 'TestGroup' for g in not_for_user))

    def test_create_and_delete_group(self):
        form = GroupCreateForm(data={'name': 'NewGroup'})
        self.assertTrue(form.is_valid())
        group = create_group(form)
        self.assertTrue(Group.objects.filter(name='NewGroup').exists())
        delete_form = GroupDeleteForm(data={'group': group.pk})
        delete_form.is_valid()
        delete_form.cleaned_data = {'group': group}
        delete_group(delete_form)
        self.assertFalse(Group.objects.filter(name='NewGroup').exists())

    def test_add_and_remove_user_to_group(self):
        """Test adding and removing user from group using form save methods."""

        factory = RequestFactory()
        request = factory.get('/')
        SessionMiddleware(lambda: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda: None).process_request(request)

        add_form = AddUserToGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk},
        )
        self.assertTrue(add_form.is_valid())
        add_form.save(request)
        self.assertIn(self.group, self.user.groups.all())

        remove_form = DeleteUserFromGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk},
        )
        self.assertTrue(remove_form.is_valid())
        remove_form.save(request)
        self.assertNotIn(self.group, self.user.groups.all())
