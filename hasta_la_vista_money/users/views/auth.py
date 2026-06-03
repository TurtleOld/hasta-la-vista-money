from typing import Any

from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.forms import BaseForm
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, View

from hasta_la_vista_money import constants
from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    set_auth_cookies,
)
from hasta_la_vista_money.users.forms import (
    RegisterByInviteForm,
    RegisterUserForm,
    UserLoginForm,
)
from hasta_la_vista_money.users.models import (
    FamilyInvite,
    User,
)
from hasta_la_vista_money.users.services.auth import login_user
from hasta_la_vista_money.users.services.groups import accept_family_invite
from hasta_la_vista_money.users.services.password import set_user_password
from hasta_la_vista_money.users.services.registration import (
    register_invited_user,
    register_user,
)


class LoginUser(SuccessMessageMixin[UserLoginForm], LoginView):
    model = User
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = constants.SUCCESS_MESSAGE_LOGIN
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        """Return the URL to redirect to after successful login."""
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return next_url
        return '/finance_account/'

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

        if result.get('success'):
            self.jwt_access_token = result.get('access', '')
            self.jwt_refresh_token = result.get('refresh', '')
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
        cache.delete('has_superuser')
        return response


class RegisterByInviteView(View):
    """Registration page for users arriving via a family-group invite token."""

    template_name = 'users/register_by_invite.html'

    def _get_invite(self, token: str) -> FamilyInvite | None:
        invite = (
            FamilyInvite.objects.filter(token=token, is_active=True)
            .select_related('group')
            .first()
        )
        if invite is None or invite.is_expired():
            return None
        return invite

    def get(
        self,
        request: HttpRequest,
        token: str,
    ) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect('users:groups:join', token=token)
        invite = self._get_invite(token)
        if invite is None:
            messages.error(
                request,
                _('Ссылка приглашения недействительна или истекла.'),
            )
            return redirect('users:login')
        form = RegisterByInviteForm()
        return render(
            request,
            self.template_name,
            {'form': form, 'invite': invite, 'token': token},
        )

    def post(
        self,
        request: HttpRequest,
        token: str,
    ) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect('users:groups:join', token=token)
        invite = self._get_invite(token)
        if invite is None:
            messages.error(
                request,
                _('Ссылка приглашения недействительна или истекла.'),
            )
            return redirect('users:login')
        form = RegisterByInviteForm(request.POST)
        if form.is_valid():
            user = register_invited_user(form)
            accept_family_invite(user, token)
            messages.success(
                request,
                _('Аккаунт создан. Войдите, чтобы продолжить.'),
            )
            return redirect('users:login')
        return render(
            request,
            self.template_name,
            {'form': form, 'invite': invite, 'token': token},
        )


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
