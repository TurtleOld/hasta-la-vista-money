import json
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.forms import BaseForm
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, UpdateView

from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import CustomSuccessURLUserMixin
from hasta_la_vista_money.users.forms import (
    UpdateUserForm,
)
from hasta_la_vista_money.users.models import (
    User,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    get_user_detailed_statistics,
)
from hasta_la_vista_money.users.services.export import get_user_export_data
from hasta_la_vista_money.users.services.notifications import (
    get_user_notifications,
)
from hasta_la_vista_money.users.services.profile import update_user_profile
from hasta_la_vista_money.users.services.theme import set_user_theme

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class ListUsers(
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    TemplateView,
):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'users'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        user_update = UpdateUserForm(instance=user)
        user_update_pass_form = PasswordChangeForm(
            user=user,
        )
        container = cast('RequestWithContainer', self.request).container
        statistics_service = container.users.user_statistics_service()
        user_statistics = statistics_service.get_user_statistics(
            user,
        )
        context['user_update'] = user_update
        context['user_update_pass_form'] = user_update_pass_form
        context['user_statistics'] = user_statistics
        context['user'] = user
        return context


class UpdateUserView(
    CustomSuccessURLUserMixin,
    SuccessMessageMixin[UpdateUserForm],
    UpdateView[User, UpdateUserForm],
):
    model = User
    template_name = 'users/profile.html'
    form_class = UpdateUserForm
    success_message = constants.SUCCESS_MESSAGE_CHANGED_PROFILE

    def get_form(self, form_class: Any = None) -> UpdateUserForm:
        form = super().get_form(form_class)
        form.instance = cast('User', self.request.user)
        return form

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user_update = self.get_form()
        valid_form = (
            user_update.is_valid()
            and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        )
        if valid_form:
            update_user_profile(user_update)
            messages.success(request, self.success_message)
            response_data = {'success': True, 'errors': {}}
        else:
            response_data = {'success': False, 'errors': user_update.errors}
        return JsonResponse(response_data)


class ExportUserDataView(LoginRequiredMixin, View):
    """View for exporting user data.

    Provides JSON export of all user financial data including accounts,
    expenses, income, and receipts.
    """

    def get(
        self,
        request: HttpRequest,
    ) -> HttpResponse:
        if not isinstance(request.user, User):
            return HttpResponse('Unauthorized', status=401)
        user_data = get_user_export_data(request.user)
        response = HttpResponse(
            json.dumps(user_data, ensure_ascii=False, indent=2, default=str),
            content_type='application/json',
        )
        response['Content-Disposition'] = (
            'attachment; filename="user_data_{}_{}.json"'.format(
                request.user.username,
                timezone.now().strftime('%Y%m%d'),
            )
        )
        return response


class UserStatisticsView(LoginRequiredMixin, TemplateView):
    """View for user detailed statistics.

    Displays comprehensive user statistics including monthly data,
    top categories, and financial overview.
    """

    template_name = 'users/statistics.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        request_with_container = cast('RequestWithContainer', self.request)
        if isinstance(user, User):
            context.update(
                get_user_detailed_statistics(
                    user,
                    container=request_with_container.container,
                ).items(),
            )
        return context


class UserNotificationsView(LoginRequiredMixin, TemplateView):
    """View for user notifications.

    Displays user notifications including low balance warnings,
    expense over income alerts, and savings achievements.
    """

    template_name = 'users/notifications.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if isinstance(user, User):
            context['notifications'] = get_user_notifications(user)
        context['user'] = user
        return context


class SwitchThemeView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
    ) -> JsonResponse:
        try:
            user = User.objects.get(pk=request.user.pk)
            data = json.loads(request.body)
            theme = data.get('theme', 'light')

            if theme not in ['light', 'dark']:
                return JsonResponse(
                    {'success': False, 'error': 'Invalid theme'},
                    status=400,
                )

            set_user_theme(user, theme)
            return JsonResponse({'success': True, 'theme': theme})
        except json.JSONDecodeError:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON'},
                status=400,
            )
        except User.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'User not found'},
                status=404,
            )
