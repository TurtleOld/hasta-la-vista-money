from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    FAMILY_INVITE_TTL,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.forms import (
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
    RegisterByInviteForm,
)
from hasta_la_vista_money.users.models import (
    FamilyGroupMembership,
    FamilyInvite,
)
from hasta_la_vista_money.users.services.groups import (
    GroupDict,
    accept_family_invite,
    create_group,
    delete_group,
    get_family_groups,
    get_or_create_family_invite,
    get_user_groups,
    remove_user_from_group,
    user_can_manage_group,
    user_has_group_access,
)
from hasta_la_vista_money.users.services.registration import (
    register_invited_user,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


def _dummy_get_response(_request: HttpRequest) -> HttpResponse:
    return HttpResponse()


def _messages_request() -> HttpRequest:
    factory: RequestFactory = RequestFactory()
    request: HttpRequest = factory.get('/')
    SessionMiddleware(_dummy_get_response).process_request(request)
    request.session.save()
    MessageMiddleware(_dummy_get_response).process_request(request)
    return request


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

    def test_get_user_groups(self) -> None:
        self.user.groups.add(self.group)
        user_groups: list[GroupDict] = get_user_groups(self.user)
        self.assertTrue(any(g['name'] == 'TestGroup' for g in user_groups))

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

    def test_remove_user_from_group(self) -> None:
        self.user.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.user,
            role=FamilyGroupMembership.Role.VIEWER,
        )
        other: UserType = User.objects.create_user(username='other-owner')
        other.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=other,
            role=FamilyGroupMembership.Role.OWNER,
        )

        remove_user_from_group(_messages_request(), self.user, self.group)

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


class ExplicitFamilyGroupTest(TestCase):
    """Groups appear only on explicit create/accept, never on GET."""

    def setUp(self) -> None:
        self.alice: UserType = User.objects.create_user(
            username='alice',
            password='testpass123',  # nosec B106: test-only password
        )
        self.mallory: UserType = User.objects.create_user(
            username='mallory',
            password='testpass123',  # nosec B106: test-only password
        )

    def _make_group(self, owner: UserType, name: str = 'Alice family') -> Group:
        form = GroupCreateForm(data={'name': name})
        form.current_user = owner
        self.assertTrue(form.is_valid())
        return create_group(form)

    def test_profile_get_without_groups_creates_nothing(self) -> None:
        self.client.force_login(self.alice)

        response = self.client.get(
            reverse('users:profile', kwargs={'pk': self.alice.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Group.objects.count(), 0)
        self.assertEqual(FamilyGroupMembership.objects.count(), 0)

    def test_group_forms_without_groups_create_nothing(self) -> None:
        DeleteUserFromGroupForm(current_user=self.alice)

        self.assertEqual(Group.objects.count(), 0)
        self.assertEqual(FamilyGroupMembership.objects.count(), 0)

    def test_viewer_stays_viewer_after_profile_get(self) -> None:
        group = self._make_group(self.alice)
        invite = get_or_create_family_invite(group, self.alice)
        accept_family_invite(self.mallory, invite.token)
        self.client.force_login(self.mallory)

        self.client.get(
            reverse('users:profile', kwargs={'pk': self.mallory.pk}),
        )

        self.assertEqual(
            FamilyGroupMembership.objects.get(
                group=group,
                user=self.mallory,
            ).role,
            FamilyGroupMembership.Role.VIEWER,
        )
        self.assertEqual(Group.objects.count(), 1)

    def test_family_scope_does_not_expose_other_user_accounts(self) -> None:
        alice_account = Account.objects.create(
            user=self.alice,
            name_account='Alice Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        alice_group = self._make_group(self.alice)
        account_service = (
            ApplicationContainer().finance_account.account_service()
        )

        for group_id in ('family', str(alice_group.pk)):
            with self.subTest(group_id=group_id):
                accounts = account_service.get_accounts_for_user_or_group(
                    self.mallory,
                    group_id,
                )
                self.assertNotIn(alice_account, accounts)

    def test_last_owner_deletes_group_and_keeps_user_data(self) -> None:
        account = Account.objects.create(
            user=self.alice,
            name_account='Alice Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        group = self._make_group(self.alice)
        get_or_create_family_invite(group, self.alice)

        form = GroupDeleteForm(
            data={'group': group.pk},
            current_user=self.alice,
        )
        self.assertTrue(form.is_valid())
        delete_group(form)  # type: ignore[arg-type]

        self.assertFalse(Group.objects.filter(pk=group.pk).exists())
        self.assertFalse(FamilyGroupMembership.objects.exists())
        self.assertFalse(FamilyInvite.objects.exists())
        self.assertTrue(Account.objects.filter(pk=account.pk).exists())

    def test_not_last_owner_cannot_delete_group(self) -> None:
        group = self._make_group(self.alice)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.mallory,
            role=FamilyGroupMembership.Role.OWNER,
        )

        form = GroupDeleteForm(
            data={'group': group.pk},
            current_user=self.alice,
        )

        self.assertFalse(form.is_valid())
        self.assertTrue(Group.objects.filter(pk=group.pk).exists())

    def test_group_forms_list_only_owned_groups(self) -> None:
        alice_group = self._make_group(self.alice, 'Alice family')
        mallory_group = self._make_group(self.mallory, 'Mallory family')

        form = DeleteUserFromGroupForm(
            data={'user': self.alice.pk},
            current_user=self.alice,
        )
        groups = form.fields['group'].queryset  # type: ignore[attr-defined]
        self.assertIn(alice_group, groups)
        self.assertNotIn(mallory_group, groups)

    def test_last_owner_cannot_be_removed_from_group(self) -> None:
        group = self._make_group(self.alice)

        remove_user_from_group(_messages_request(), self.alice, group)

        self.assertTrue(user_can_manage_group(self.alice, group))
        self.assertIn(group, self.alice.groups.all())

    def test_owner_can_be_removed_when_another_owner_exists(self) -> None:
        group = self._make_group(self.alice)
        self.mallory.groups.add(group)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.mallory,
            role=FamilyGroupMembership.Role.OWNER,
        )

        remove_user_from_group(_messages_request(), self.alice, group)

        self.assertNotIn(group, self.alice.groups.all())
        self.assertTrue(user_can_manage_group(self.mallory, group))

    def test_invite_does_not_change_existing_role(self) -> None:
        group = self._make_group(self.alice)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.mallory,
            role=FamilyGroupMembership.Role.VIEWER,
        )
        invite = get_or_create_family_invite(
            group,
            self.alice,
            role=FamilyGroupMembership.Role.OWNER,
        )

        accept_family_invite(self.mallory, invite.token)

        self.assertEqual(
            FamilyGroupMembership.objects.get(
                group=group,
                user=self.mallory,
            ).role,
            FamilyGroupMembership.Role.VIEWER,
        )


class DirectGroupMembershipTest(TestCase):
    """Membership changes only via invites; removal is scoped by role."""

    def setUp(self) -> None:
        self.owner: UserType = User.objects.create_user(
            username='owner',
            password='testpass123',  # nosec B106: test-only password
        )
        self.viewer: UserType = User.objects.create_user(
            username='viewer',
            password='testpass123',  # nosec B106: test-only password
        )
        self.stranger: UserType = User.objects.create_user(
            username='stranger',
            password='testpass123',  # nosec B106: test-only password
        )
        form = GroupCreateForm(data={'name': 'Family'})
        form.current_user = self.owner
        self.assertTrue(form.is_valid())
        self.group: Group = create_group(form)
        invite = get_or_create_family_invite(self.group, self.owner)
        accept_family_invite(self.viewer, invite.token)

    def _remove(self, who: UserType, target: UserType) -> None:
        self.client.force_login(who)
        self.client.post(
            reverse('users:groups:delete_user'),
            {'user': target.pk, 'group': self.group.pk},
        )

    def test_direct_add_route_is_gone(self) -> None:
        self.client.force_login(self.owner)

        response = self.client.post(
            '/users/groups/add-user/',
            {'user': self.stranger.pk, 'group': self.group.pk},
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.group, self.stranger.groups.all())

    def test_group_form_does_not_list_all_users(self) -> None:
        form = DeleteUserFromGroupForm(current_user=self.owner)

        users = form.fields['user'].queryset  # type: ignore[attr-defined]

        self.assertIn(self.viewer, users)
        self.assertNotIn(self.stranger, users)

    def test_viewer_cannot_remove_other_member(self) -> None:
        self._remove(self.viewer, self.owner)

        self.assertIn(self.group, self.owner.groups.all())

    def test_owner_can_remove_viewer(self) -> None:
        self._remove(self.owner, self.viewer)

        self.assertNotIn(self.group, self.viewer.groups.all())

    def test_viewer_can_leave_group(self) -> None:
        self._remove(self.viewer, self.viewer)

        self.assertNotIn(self.group, self.viewer.groups.all())

    def test_last_owner_cannot_leave_with_other_members(self) -> None:
        self._remove(self.owner, self.owner)

        self.assertIn(self.group, self.owner.groups.all())
        self.assertTrue(user_can_manage_group(self.owner, self.group))


class InviteExpiryTest(TestCase):
    """Tests for invite expiry logic."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            raise ValueError('No user found in fixtures')
        self.user: UserType = user
        self.group: Group = Group.objects.create(name='ExpiryTestGroup')
        self.user.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )

    def test_expired_invite_is_rejected(self) -> None:
        invite = get_or_create_family_invite(self.group, self.user)
        invite.expires_at = timezone.now() - timedelta(hours=1)
        invite.save(update_fields=['expires_at'])

        second_user_data = {
            'username': 'invited_user',
            'email': 'invited@example.com',
            'password1': 'StrongPassword123',
            'password2': 'StrongPassword123',
        }
        form = RegisterByInviteForm(data=second_user_data)
        self.assertTrue(form.is_valid())
        second_user = register_invited_user(form)

        result = accept_family_invite(second_user, invite.token)
        self.assertIsNone(result)
        self.assertNotIn(self.group, second_user.groups.all())

    def test_valid_invite_registers_and_joins(self) -> None:
        invite = get_or_create_family_invite(self.group, self.user)
        invite.expires_at = timezone.now() + timedelta(days=7)
        invite.save(update_fields=['expires_at'])

        second_user_data = {
            'username': 'invited_valid',
            'email': 'valid@example.com',
            'password1': 'StrongPassword123',
            'password2': 'StrongPassword123',
        }
        form = RegisterByInviteForm(data=second_user_data)
        self.assertTrue(form.is_valid())
        second_user = register_invited_user(form)

        self.assertFalse(second_user.is_superuser)
        self.assertFalse(second_user.is_staff)

        result = accept_family_invite(second_user, invite.token)
        self.assertIsNotNone(result)
        self.assertIn(self.group, second_user.groups.all())
        self.assertTrue(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=second_user,
                role=FamilyGroupMembership.Role.VIEWER,
            ).exists(),
        )


class RegisterByInviteViewTest(TestCase):
    """Tests for RegisterByInviteView."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        owner = User.objects.first()
        if owner is None:
            raise ValueError('No user found in fixtures')
        self.owner: UserType = owner
        self.group: Group = Group.objects.create(name='ViewTestGroup')
        self.owner.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=FamilyGroupMembership.Role.OWNER,
        )
        self.invite = get_or_create_family_invite(self.group, self.owner)

    def test_get_shows_registration_form(self) -> None:
        url = f'/users/groups/register/{self.invite.token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)

    def test_invalid_token_redirects_to_login(self) -> None:
        response = self.client.get('/users/groups/register/invalidtoken123/')
        self.assertRedirects(response, '/users/login/')

    def test_post_creates_user_and_joins_group(self) -> None:
        url = f'/users/groups/register/{self.invite.token}/'
        data = {
            'username': 'newmember',
            'email': 'newmember@example.com',
            'password1': 'StrongPassword123',
            'password2': 'StrongPassword123',
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, '/users/login/')
        new_user = User.objects.get(username='newmember')
        self.assertFalse(new_user.is_superuser)
        self.assertIn(self.group, new_user.groups.all())

    def test_authenticated_user_is_redirected_to_join(self) -> None:
        self.client.force_login(self.owner)
        url = f'/users/groups/register/{self.invite.token}/'
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f'/users/groups/join/{self.invite.token}/',
            fetch_redirect_response=False,
        )


class FamilyInviteTtlTest(TestCase):
    """Family invites expire and rotate when members are removed."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        owner = User.objects.first()
        if owner is None:
            self.fail('No user found in fixtures')
        self.owner: UserType = owner
        self.group: Group = Group.objects.create(name='TtlGroup')
        self.owner.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=FamilyGroupMembership.Role.OWNER,
        )

    def test_new_invite_receives_default_ttl(self) -> None:
        invite = get_or_create_family_invite(self.group, self.owner)

        expires_at = invite.expires_at
        if expires_at is None:
            self.fail('expires_at was not set for a new invite')

        expected = timezone.now() + FAMILY_INVITE_TTL
        self.assertLessEqual(abs(expires_at - expected), timedelta(minutes=1))

    def test_expired_active_invite_is_not_reused(self) -> None:
        invite = get_or_create_family_invite(self.group, self.owner)
        invite.expires_at = timezone.now() - timedelta(minutes=1)
        invite.save(update_fields=['expires_at'])

        refreshed = get_or_create_family_invite(self.group, self.owner)

        self.assertNotEqual(refreshed.pk, invite.pk)
        refreshed_expires = refreshed.expires_at
        if refreshed_expires is None:
            self.fail('expires_at was not set for a refreshed invite')
        self.assertGreater(refreshed_expires, timezone.now())

    def test_removing_member_rotates_active_invite(self) -> None:
        member: UserType = User.objects.create_user(
            username='removed-member',
            password='testpass123',  # nosec B106: test-only password
        )
        invite = get_or_create_family_invite(self.group, self.owner)
        accept_family_invite(member, invite.token)
        self.assertIn(self.group, member.groups.all())

        remove_user_from_group(_messages_request(), member, self.group)
        self.assertNotIn(self.group, member.groups.all())

        other: UserType = User.objects.create_user(
            username='other-member',
            password='testpass123',  # nosec B106: test-only password
        )
        self.assertIsNone(accept_family_invite(other, invite.token))
        self.assertNotIn(self.group, other.groups.all())

        new_invite = get_or_create_family_invite(self.group, self.owner)
        self.assertNotEqual(new_invite.token, invite.token)
        self.assertTrue(new_invite.is_active)


class JoinFamilyGroupViewTest(TestCase):
    """GET must not mutate membership; only a CSRF-protected POST joins."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        owner = User.objects.first()
        if owner is None:
            self.fail('No user found in fixtures')
        self.owner: UserType = owner
        self.group: Group = Group.objects.create(name='JoinGroup')
        self.owner.groups.add(self.group)
        FamilyGroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=FamilyGroupMembership.Role.OWNER,
        )
        self.invite = get_or_create_family_invite(self.group, self.owner)
        self.joiner: UserType = User.objects.create_user(
            username='joiner',
            email='joiner@example.com',
            password='testpass123',  # nosec B106: test-only password
        )

    def _url(self) -> str:
        return f'/users/groups/join/{self.invite.token}/'

    def _profile_url(self) -> str:
        return f'/users/profile/{self.joiner.pk}/'

    def test_get_shows_confirmation_without_joining(self) -> None:
        self.client.force_login(self.joiner)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)
        self.assertContains(response, self.owner.username)
        self.assertNotIn(self.group, self.joiner.groups.all())
        self.assertFalse(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.joiner,
            ).exists(),
        )

    def test_post_joins_group(self) -> None:
        self.client.force_login(self.joiner)

        response = self.client.post(self._url())

        self.assertRedirects(response, self._profile_url())
        self.assertIn(self.group, self.joiner.groups.all())
        self.assertTrue(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.joiner,
                role=FamilyGroupMembership.Role.VIEWER,
            ).exists(),
        )

    def test_expired_token_is_rejected(self) -> None:
        self.invite.expires_at = timezone.now() - timedelta(minutes=1)
        self.invite.save(update_fields=['expires_at'])
        self.client.force_login(self.joiner)

        for method in ('get', 'post'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self._url())
                self.assertRedirects(response, self._profile_url())
                self.assertNotIn(self.group, self.joiner.groups.all())

    def test_expired_token_shows_clear_message(self) -> None:
        self.invite.expires_at = timezone.now() - timedelta(minutes=1)
        self.invite.save(update_fields=['expires_at'])
        self.client.force_login(self.joiner)

        response = self.client.get(self._url(), follow=True)

        self.assertContains(response, 'недействительна или истекла')

    def test_unauthenticated_user_is_redirected_to_registration(self) -> None:
        response = self.client.get(self._url())

        self.assertRedirects(
            response,
            f'/users/groups/register/{self.invite.token}/',
            fetch_redirect_response=False,
        )

    def test_post_without_csrf_token_is_rejected(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.joiner)

        response = client.post(self._url())

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.group, self.joiner.groups.all())
