"""Typed boundary for Django's swap-aware user model.

The project fixes ``AUTH_USER_MODEL`` to :class:`users.User`; pyright cannot
infer that from ``get_user_model()`` (it returns ``type[AbstractBaseUser]``),
so this helper narrows the boundary once. The import of ``User`` stays
type-only and Django's runtime resolver is called lazily, preserving app
registry timing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth import get_user_model as django_get_user_model

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def get_user_model() -> type[User]:
    """Return the project user model with its concrete typing."""
    user_model = django_get_user_model()
    meta_name = '_meta'
    return cast('type[User]', getattr(user_model, meta_name).model)


__all__ = ['get_user_model']
