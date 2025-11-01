import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.forms import BaseForm
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView
from django.views.generic.edit import FormView

from hasta_la_vista_money import constants
from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    set_auth_cookies,
)
from hasta_la_vista_money.custom_mixin import CustomSuccessURLUserMixin
from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
    RegisterUserForm,
    UpdateUserForm,
    UserLoginForm,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.auth import login_user
from hasta_la_vista_money.users.services.detailed_statistics import (
    get_user_detailed_statistics,
)
from hasta_la_vista_money.users.services.export import get_user_export_data
from hasta_la_vista_money.users.services.groups import (
    create_group,
    delete_group,
    get_groups_not_for_user,
    get_user_groups,
    remove_user_from_group,
)
from hasta_la_vista_money.users.services.notifications import (
    get_user_notifications,
)
from hasta_la_vista_money.users.services.password import set_user_password
from hasta_la_vista_money.users.services.profile import update_user_profile
from hasta_la_vista_money.users.services.registration import register_user
from hasta_la_vista_money.users.services.statistics import get_user_statistics
from hasta_la_vista_money.users.services.theme import set_user_theme


class IndexView(TemplateView):
    def dispatch(
        self,
        request: HttpRequest,
    ) -> HttpResponseBase:
        if request.user.is_authenticated:
            return redirect('applications:list')
        return redirect('login')


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
        if self.request.user.is_authenticated:
            user_update = UpdateUserForm(instance=self.request.user)
            user_update_pass_form = PasswordChangeForm(
                user=self.request.user,
            )
            if isinstance(self.request.user, User):
                user_statistics = get_user_statistics(self.request.user)
            else:
                user_statistics = None

            context['user_update'] = user_update
            context['user_update_pass_form'] = user_update_pass_form
            context['user_statistics'] = user_statistics
            context['user'] = self.request.user
        return context


class LoginUser(SuccessMessageMixin[UserLoginForm], LoginView):
    model = User
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = constants.SUCCESS_MESSAGE_LOGIN
    next_page: str = str(reverse_lazy('applications:list'))
    redirect_authenticated_user = True

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if not hasattr(request, 'axes_checked'):
            request.axes_checked = True  # type: ignore[attr-defined]
            if hasattr(request, 'axes_locked_out'):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'success': False,
                            'error': (
                                'Слишком много неудачных попыток входа. '
                                'Ваш браузер и компьютер заблокированы '
                                'для входа в это приложение. '
                                'Попробуйте позже или '
                                'обратитесь к администратору.'
                            ),
                        },
                        status=429,
                    )
                messages.error(
                    request,
                    'Слишком много неудачных попыток входа. '
                    'Ваш браузер и компьютер заблокированы '
                    'для входа в это приложение. '
                    'Попробуйте позже или обратитесь к администратору.',
                )
                return self.render_to_response(self.get_context_data())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['button_text'] = _('Войти')
        if 'form' in context:
            context['user_login_form'] = context['form']
        else:
            context['user_login_form'] = UserLoginForm()
        if hasattr(self, 'jwt_access_token'):
            context['jwt_access_token'] = self.jwt_access_token
        if hasattr(self, 'jwt_refresh_token'):
            context['jwt_refresh_token'] = self.jwt_refresh_token
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        result = login_user(self.request, form, str(self.success_message))
        is_ajax = (
            self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
        )

        if result['success']:
            self.jwt_access_token = result['access']
            self.jwt_refresh_token = result['refresh']
            if is_ajax:
                response: HttpResponse = JsonResponse(
                    {
                        'redirect_url': self.get_success_url(),
                    },
                )
            else:
                response = redirect(self.get_success_url())

            access_token: str | None = self.jwt_access_token
            refresh_token: str | None = self.jwt_refresh_token
            if access_token is None:
                return response
            return set_auth_cookies(
                response,
                access_token,
                refresh_token,
            )

        error_message = 'Неправильный логин или пароль!'
        messages.error(self.request, error_message)

        if is_ajax:
            return JsonResponse({'success': False, 'error': error_message})
        form.add_error(None, error_message)
        return self.form_invalid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            errors = {}
            for field, field_errors in form.errors.items():
                error_msg = field_errors[0] if field_errors else ''
                errors[field] = error_msg
                if error_msg and field != '__all__':
                    messages.error(self.request, f'{field}: {error_msg}')

            if form.non_field_errors():
                for error in form.non_field_errors():
                    messages.error(self.request, str(error))

            return JsonResponse({'success': False, 'errors': errors})

        return self.render_to_response(self.get_context_data(form=form))


class LogoutUser(LogoutView, SuccessMessageMixin[BaseForm]):
    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        messages.add_message(
            request,
            messages.SUCCESS,
            constants.SUCCESS_MESSAGE_LOGOUT,
        )
        response = super().dispatch(request, *args, **kwargs)
        return clear_auth_cookies(response)


class CreateUser(
    SuccessMessageMixin[RegisterUserForm],
    CreateView[User, RegisterUserForm],
):
    model = User
    template_name = 'users/registration.html'
    form_class = RegisterUserForm
    success_message = constants.SUCCESS_MESSAGE_REGISTRATION
    success_url = reverse_lazy('login')

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if User.objects.filter(is_superuser=True).exists():
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['title'] = _('Форма регистрации')
        context['button_text'] = _('Регистрация')
        return context

    def form_valid(self, form: RegisterUserForm) -> HttpResponse:
        response = super().form_valid(form)
        register_user(form)
        return response


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
        form.instance = self.request.user
        return form

    def post(
        self,
        request: HttpRequest,
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


class SetPasswordUserView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'users/set_password.html'
    form_class = SetPasswordForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.request.user.pk)
        if self.request.method == 'POST':
            context['form_password'] = SetPasswordForm(
                user=user,
                data=self.request.POST,
            )
            context['user'] = user
        else:
            context['form_password'] = SetPasswordForm(user=user)
        return context

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:  # type: ignore[type-arg]
        set_user_password(form, self.request)
        messages.success(
            self.request,
            f'Пароль успешно установлен для пользователя {form.user}',
        )
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk},
            ),
        )


class ExportUserDataView(LoginRequiredMixin, View):
    """Представление для экспорта данных пользователя"""

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
    """Представление для детальной статистики пользователя"""

    template_name = 'users/statistics.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if isinstance(user, User):
            context.update(get_user_detailed_statistics(user).items())
        return context


class UserNotificationsView(LoginRequiredMixin, TemplateView):
    """Представление для уведомлений пользователя"""

    template_name = 'users/notifications.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if isinstance(user, User):
            context['notifications'] = get_user_notifications(user)
        context['user'] = user
        return context


class GroupCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[GroupCreateForm],
    FormView[GroupCreateForm],
):
    template_name = 'users/group_create.html'
    form_class = GroupCreateForm
    success_message = _('Группа успешно создана')

    def form_valid(self, form: GroupCreateForm) -> HttpResponse:
        create_group(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class GroupDeleteView(
    LoginRequiredMixin,
    SuccessMessageMixin[GroupDeleteForm],
    FormView[GroupDeleteForm],
):
    template_name = 'users/group_delete.html'
    form_class = GroupDeleteForm
    success_message = _('Группа успешно удалена.')

    def form_valid(self, form: GroupDeleteForm) -> HttpResponse:
        delete_group(form)  # type: ignore[arg-type]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class AddUserToGroupView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddUserToGroupForm],
    FormView[AddUserToGroupForm],
):
    template_name = 'users/add_user_to_group.html'
    form_class = AddUserToGroupForm
    success_message = _('Пользователь успешно добавлен в группу')

    def form_valid(self, form: AddUserToGroupForm) -> HttpResponse:
        form.save(self.request)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class DeleteUserFromGroupView(
    LoginRequiredMixin,
    SuccessMessageMixin[DeleteUserFromGroupForm],
    FormView[DeleteUserFromGroupForm],
):
    template_name = 'users/delete_user_from_group.html'
    form_class = DeleteUserFromGroupForm
    success_message = _('Пользователь успешно удален из группы')

    def form_valid(self, form: DeleteUserFromGroupForm) -> HttpResponse:
        remove_user_from_group(
            self.request,
            form.cleaned_data['user'],
            form.cleaned_data['group'],
        )
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


def groups_for_user_ajax(request: HttpRequest) -> JsonResponse:
    user_id = request.GET.get('user_id')
    groups = []
    if user_id:
        try:
            user = User.objects.get(pk=user_id)
            groups = get_user_groups(user)
        except User.DoesNotExist:
            pass
    return JsonResponse({'groups': groups})


def groups_not_for_user_ajax(request: HttpRequest) -> JsonResponse:
    user_id = request.GET.get('user_id')
    groups = []
    if user_id:
        try:
            user = User.objects.get(pk=user_id)
            groups = get_groups_not_for_user(user)
        except User.DoesNotExist:
            pass
    return JsonResponse({'groups': groups})


class SwitchThemeView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
    ) -> JsonResponse:
        user = User.objects.get(pk=request.user.pk or 0)
        data = json.loads(request.body)
        theme = data.get('theme')
        set_user_theme(user, theme)
        return JsonResponse({'success': True})
