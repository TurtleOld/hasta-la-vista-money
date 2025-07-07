from typing import Any
from django.contrib import admin
from django.db.models import CharField
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    theme: CharField[Any, Any] = CharField(max_length=10, default='dark')

    def __str__(self) -> str:
        return self.username


class TokenAdmin(admin.ModelAdmin):  # type: ignore
    search_fields = ('key', 'user__username')
