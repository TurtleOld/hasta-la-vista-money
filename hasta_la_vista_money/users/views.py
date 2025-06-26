from django.contrib import messages
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, TemplateView, UpdateView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.generate_dates import generate_date_list
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    CustomSuccessURLUserMixin,
)
from hasta_la_vista_money.users.forms import (
    RegisterUserForm,
    UpdateUserForm,
    UserLoginForm,
)
from hasta_la_vista_money.users.models import User
from rest_framework_simplejwt.tokens import RefreshToken


class IndexView(TemplateView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('applications:list')
        return redirect('login')


class ListUsers(CustomNoPermissionMixin, SuccessMessageMixin, TemplateView):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'users'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            user_update = UpdateUserForm(instance=self.request.user)
            user_update_pass_form = PasswordChangeForm(
                user=self.request.user,
            )
            context['user_update'] = user_update
            context['user_update_pass_form'] = user_update_pass_form
        return context


class LoginUser(SuccessMessageMixin, LoginView):
    model = User
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = constants.SUCCESS_MESSAGE_LOGIN
    next_page = '/hasta-la-vista-money'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['button_text'] = _('Войти')
        context['user_login_form'] = UserLoginForm()
        if hasattr(self, "jwt_access_token"):
            context["jwt_access_token"] = self.jwt_access_token
        if hasattr(self, "jwt_refresh_token"):
            context["jwt_refresh_token"] = self.jwt_refresh_token
        return context

    def form_valid(self, form):
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        user = authenticate(
            self.request,
            username=username,
            password=password,
            backend='django.contrib.auth.backends.ModelBackend',
        )
        if user is not None:
            login(self.request, user)
            tokens = RefreshToken.for_user(user)
            self.jwt_access_token = str(tokens.access_token)
            self.jwt_refresh_token = str(tokens)
            return self.render_to_response(
                self.get_context_data(redirect_to=self.get_success_url())
            )
        messages.error(self.request, _('Неправильный логин или пароль!'))
        return self.form_invalid(form)

    def form_invalid(self, form):
        if form.errors:
            messages.error(
                self.request,
                list(form.errors.values())[0][0],
            )
        return super().form_invalid(form)


class LogoutUser(LogoutView, SuccessMessageMixin):
    def dispatch(self, request, *args, **kwargs):
        messages.add_message(
            request,
            messages.SUCCESS,
            constants.SUCCESS_MESSAGE_LOGOUT,
        )
        return super().dispatch(request, *args, **kwargs)


class CreateUser(SuccessMessageMixin, CreateView):
    model = User
    template_name = 'users/registration.html'
    form_class = RegisterUserForm
    success_message = constants.SUCCESS_MESSAGE_REGISTRATION
    success_url = reverse_lazy('login')

    def dispatch(self, request, *args, **kwargs):
        if User.objects.filter(is_superuser=True).exists():
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _('Форма регистрации')
        context['button_text'] = _('Регистрация')
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.is_superuser = True
        self.object.is_staff = True
        self.object.save()
        date_time_user_registration = self.object.date_joined
        generate_date_list(date_time_user_registration, self.object)
        return response


class UpdateUserView(
    CustomSuccessURLUserMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = User
    template_name = 'users/profile.html'
    form_class = UpdateUserForm
    success_message = constants.SUCCESS_MESSAGE_CHANGED_PROFILE

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance = self.request.user
        return form

    def post(self, request, *args, **kwargs):
        user_update = self.get_form()
        valid_form = (
            user_update.is_valid()
            and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        )
        if valid_form:
            user_update.save()
            messages.success(request, self.success_message)
            response_data = {'success': True}
        else:
            response_data = {'success': False, 'errors': user_update.errors}
        return JsonResponse(response_data)


class SetPasswordUserView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'users/set_password.html'
    form_class = SetPasswordForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.request.user.pk)
        if self.request.method == 'POST':
            context['form_password'] = self.form_class(
                user=user,
                data=self.request.POST,
            )
            context['user'] = user
        else:
            context['form_password'] = self.form_class(user=user)
        return context

    def form_valid(self, form):
        form.save()
        update_session_auth_hash(request=self.request, user=form.user)
        messages.success(
            self.request,
            f'Пароль успешно установлен для пользователя {form.user}',
        )
        return super().form_valid(form)

    def get_success_url(self):
        # Генерируем URL для профиля пользователя с использованием его pk
        return reverse_lazy(
            'users:profile',
            kwargs={'pk': self.request.user.pk},
        )
