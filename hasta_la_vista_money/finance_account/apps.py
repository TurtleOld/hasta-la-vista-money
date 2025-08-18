"""Django app configuration for finance account management.

This module configures the finance_account Django app, defining its metadata
and initialization settings for the Django application framework.
"""

from django.apps import AppConfig


class AccountConfig(AppConfig):
    """Configuration class for the finance_account Django app.

    Defines the app's metadata including the default auto field type
    and the app's package name within the Django project.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.finance_account'
