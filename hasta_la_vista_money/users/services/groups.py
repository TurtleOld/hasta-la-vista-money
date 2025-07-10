from typing import List, Dict
from django.contrib.auth.models import Group
from hasta_la_vista_money.users.models import User


def get_user_groups(user: User) -> List[Dict]:
    return list(user.groups.values('id', 'name'))


def get_groups_not_for_user(user: User) -> List[Dict]:
    return list(
        Group.objects.exclude(id__in=user.groups.values_list('id', flat=True)).values(
            'id', 'name'
        )
    )


def create_group(form) -> Group:
    return form.save()


def delete_group(form) -> None:
    group = form.cleaned_data['group']
    group.delete()


def add_user_to_group(form) -> None:
    user = form.cleaned_data['user']
    group = form.cleaned_data['group']
    user.groups.add(group)


def remove_user_from_group(form) -> None:
    user = form.cleaned_data['user']
    group = form.cleaned_data['group']
    user.groups.remove(group)
