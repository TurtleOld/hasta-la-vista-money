"""Unit tests for user app URL configuration."""

from django.test import SimpleTestCase
from django.urls import reverse, resolve
from hasta_la_vista_money.users.views import (
    CreateUser,
    ListUsers,
    LoginUser,
    SetPasswordUserView,
    UpdateUserView,
    UserStatisticsView,
    ExportUserDataView,
    SwitchThemeView,
    GroupCreateView,
    GroupDeleteView,
    AddUserToGroupView,
    DeleteUserFromGroupView,
    groups_for_user_ajax,
    groups_not_for_user_ajax,
)


class TestUserUrls(SimpleTestCase):
    """Test user authentication and profile URLs."""

    def test_registration_url_resolves(self):
        """Test that registration URL resolves to correct view."""
        url = reverse('users:registration')
        self.assertEqual(resolve(url).func.view_class, CreateUser)

    def test_profile_url_resolves(self):
        """Test that profile URL resolves to correct view."""
        url = reverse('users:profile', args=[1])
        self.assertEqual(resolve(url).func.view_class, ListUsers)

    def test_password_url_resolves(self):
        """Test that password change URL resolves to correct view."""
        url = reverse('users:password')
        self.assertEqual(resolve(url).func.view_class, SetPasswordUserView)

    def test_login_url_resolves(self):
        """Test that login URL resolves to correct view."""
        url = reverse('users:login')
        self.assertEqual(resolve(url).func.view_class, LoginUser)

    def test_update_user_url_resolves(self):
        """Test that update user URL resolves to correct view."""
        url = reverse('users:update_user', args=[1])
        self.assertEqual(resolve(url).func.view_class, UpdateUserView)

    def test_list_users_url_resolves(self):
        """Test that list users URL resolves to correct view."""
        url = reverse('users:list_users')
        self.assertEqual(resolve(url).func.view_class, ListUsers)

    def test_statistics_url_resolves(self):
        """Test that statistics URL resolves to correct view."""
        url = reverse('users:statistics')
        self.assertEqual(resolve(url).func.view_class, UserStatisticsView)

    def test_export_data_url_resolves(self):
        """Test that export data URL resolves to correct view."""
        url = reverse('users:export_data')
        self.assertEqual(resolve(url).func.view_class, ExportUserDataView)

    def test_set_theme_url_resolves(self):
        """Test that set theme URL resolves to correct view."""
        url = reverse('users:set_theme')
        self.assertEqual(resolve(url).func.view_class, SwitchThemeView)


class TestGroupUrls(SimpleTestCase):
    """Test group-related URLs."""

    def test_group_create_url_resolves(self):
        """Test that group create URL resolves to correct view."""
        url = reverse('users:groups:create')
        self.assertEqual(resolve(url).func.view_class, GroupCreateView)

    def test_group_delete_url_resolves(self):
        """Test that group delete URL resolves to correct view."""
        url = reverse('users:groups:delete')
        self.assertEqual(resolve(url).func.view_class, GroupDeleteView)

    def test_add_user_to_group_url_resolves(self):
        """Test that add user to group URL resolves to correct view."""
        url = reverse('users:groups:add_user')
        self.assertEqual(resolve(url).func.view_class, AddUserToGroupView)

    def test_delete_user_from_group_url_resolves(self):
        """Test that delete user from group URL resolves to correct view."""
        url = reverse('users:groups:delete_user')
        self.assertEqual(resolve(url).func.view_class, DeleteUserFromGroupView)


class TestAjaxUrls(SimpleTestCase):
    """Test AJAX-related URLs."""

    def test_groups_for_user_ajax_url_resolves(self):
        """Test that groups for user AJAX URL resolves to correct view."""
        url = reverse('users:ajax:groups_for_user')
        self.assertEqual(resolve(url).func, groups_for_user_ajax)

    def test_groups_not_for_user_ajax_url_resolves(self):
        """Test that groups not for user AJAX URL resolves to correct view."""
        url = reverse('users:ajax:groups_not_for_user')
        self.assertEqual(resolve(url).func, groups_not_for_user_ajax)


class TestUrlPatterns(SimpleTestCase):
    """Test URL pattern structure and naming."""

    def test_url_names_use_underscores(self):
        """Test that URL names use underscores consistently."""
        url_names_with_args = {
            'users:profile': [1],
            'users:update_user': [1],
        }
        url_names_without_args = [
            'users:registration',
            'users:password',
            'users:login',
            'users:list_users',
            'users:statistics',
            'users:export_data',
            'users:set_theme',
        ]

        # Test URLs that require arguments
        for name, args in url_names_with_args.items():
            try:
                reverse(name, args=args)
            except Exception as e:
                self.fail(f"URL name '{name}' failed to resolve: {e}")

        # Test URLs that don't require arguments
        for name in url_names_without_args:
            try:
                reverse(name)
            except Exception as e:
                self.fail(f"URL name '{name}' failed to resolve: {e}")

    def test_url_paths_use_hyphens(self):
        """Test that URL paths use hyphens consistently."""
        url_paths = [
            '/users/registration/',
            '/users/profile/1/',
            '/users/profile/password/',
            '/users/login/',
            '/users/update-user/1/',
            '/users/list/users/',
            '/users/statistics/',
            '/users/export-data/',
            '/users/set-theme/',
        ]

        for path in url_paths:
            try:
                resolve(path)
            except Exception as e:
                self.fail(f"URL path '{path}' failed to resolve: {e}")
