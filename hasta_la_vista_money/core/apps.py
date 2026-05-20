from importlib import import_module

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.core'

    def ready(self) -> None:
        import_module('hasta_la_vista_money.core.signals')
