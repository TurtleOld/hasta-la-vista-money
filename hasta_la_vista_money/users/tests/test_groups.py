from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from hasta_la_vista_money.users.services.groups import (
    get_user_groups,
    get_groups_not_for_user,
    create_group,
    delete_group,
    add_user_to_group,
    remove_user_from_group,
)
from hasta_la_vista_money.users.forms import (
    GroupCreateForm,
    GroupDeleteForm,
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
)

User = get_user_model()


class GroupsServiceTest(TestCase):
    """Tests for user group services."""

    fixtures = ['users.yaml']

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
        add_form = AddUserToGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk}
        )
        add_form.is_valid()
        add_form.cleaned_data = {'user': self.user, 'group': self.group}
        add_user_to_group(add_form)
        self.assertIn(self.group, self.user.groups.all())
        remove_form = DeleteUserFromGroupForm(
            data={'user': self.user.pk, 'group': self.group.pk}
        )
        remove_form.is_valid()
        remove_form.cleaned_data = {'user': self.user, 'group': self.group}
        remove_user_from_group(remove_form)
        self.assertNotIn(self.group, self.user.groups.all())
