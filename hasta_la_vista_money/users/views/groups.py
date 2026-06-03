from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.http import (
    HttpResponse,
)
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic.edit import FormView

from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
)
from hasta_la_vista_money.users.services.groups import (
    accept_family_invite,
    create_group,
    delete_group,
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
        form.current_user = self.request.user
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
        if not user_can_manage_group(
            self.request.user,
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


class AddUserToGroupView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddUserToGroupForm],
    FormView[AddUserToGroupForm],
):
    template_name = 'users/add_user_to_group.html'
    form_class = AddUserToGroupForm
    success_message = _('Пользователь успешно добавлен в группу')

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs['current_user'] = self.request.user
        return kwargs

    def form_valid(self, form: AddUserToGroupForm) -> HttpResponse:
        if not user_can_manage_group(
            self.request.user,
            form.cleaned_data['group'],
        ):
            raise PermissionDenied
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

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        kwargs['current_user'] = self.request.user
        return kwargs

    def form_valid(self, form: DeleteUserFromGroupForm) -> HttpResponse:
        if not user_can_manage_group(
            self.request.user,
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
    """Join a family group by share link."""

    def get(self, request, token: str) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect('users:groups:register_by_invite', token=token)
        group = accept_family_invite(request.user, token)
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
        return redirect('users:profile', pk=request.user.pk)
