from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.http import (
    HttpRequest,
    HttpResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic.edit import FormView

from hasta_la_vista_money.users.forms import (
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.groups import (
    accept_family_invite,
    create_group,
    delete_group,
    get_active_family_invite,
    remove_user_from_group,
    user_can_manage_group,
)


class GroupCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[GroupCreateForm],
    FormView[GroupCreateForm],
):
    template_name = 'users/group_create.html'
    form_class = GroupCreateForm
    success_message = _('Группа успешно создана')

    def form_valid(self, form: GroupCreateForm) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied
        form.current_user = user
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

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs['current_user'] = self.request.user
        return kwargs

    def form_valid(self, form: GroupDeleteForm) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied
        if not user_can_manage_group(
            user,
            form.cleaned_data['group'],
        ):
            raise PermissionDenied
        delete_group(form)  # type: ignore[arg-type]
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

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs['current_user'] = self.request.user
        return kwargs

    def form_valid(self, form: DeleteUserFromGroupForm) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied
        if form.cleaned_data['user'] != user and not user_can_manage_group(
            user,
            form.cleaned_data['group'],
        ):
            raise PermissionDenied
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


class JoinFamilyGroupView(View):
    """Confirm and accept a family group invite.

    Joining is a state-changing action, so a plain GET only renders a
    confirmation page. Membership changes exclusively through a
    CSRF-protected POST.
    """

    template_name = 'users/join_family_group.html'

    def _resolve_user(self, request: HttpRequest) -> User | None:
        if not request.user.is_authenticated:
            return None
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied
        return user

    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        user = self._resolve_user(request)
        if user is None:
            return redirect('users:groups:register_by_invite', token=token)
        invite = get_active_family_invite(token)
        if invite is None:
            messages.error(
                request,
                _('Ссылка приглашения недействительна или истекла.'),
            )
            return redirect('users:profile', pk=user.pk)
        return render(
            request,
            self.template_name,
            {'invite': invite, 'token': token},
        )

    def post(self, request: HttpRequest, token: str) -> HttpResponse:
        user = self._resolve_user(request)
        if user is None:
            return redirect('users:groups:register_by_invite', token=token)
        group = accept_family_invite(user, token)
        if group is None:
            messages.error(
                request,
                _('Ссылка приглашения недействительна или истекла.'),
            )
        else:
            messages.success(
                request,
                _('Вы присоединились к семейной группе «%(group)s».')
                % {'group': group.name},
            )
        return redirect('users:profile', pk=user.pk)
