from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.users'

    def ready(self) -> None:
        import hasta_la_vista_money.users.services.signals  # noqa: F401
