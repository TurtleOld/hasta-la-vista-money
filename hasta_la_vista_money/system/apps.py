from importlib import import_module

from django.apps import AppConfig


class SystemConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.system'

    def ready(self) -> None:
        import_module('hasta_la_vista_money.system.signals')
