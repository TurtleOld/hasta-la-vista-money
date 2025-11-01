from typing import Any

from django.contrib import admin
from django.contrib.auth.models import AbstractUser
from django.db.models import CharField


class User(AbstractUser):
    theme: CharField[Any, Any] = CharField(max_length=10, default='dark')

    def __str__(self) -> str:
        return str(self.username)


class TokenAdmin(admin.ModelAdmin):
    search_fields = ('key', 'user__username')
