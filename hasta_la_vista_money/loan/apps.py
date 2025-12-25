from django.apps import AppConfig


class CreditsConfig(AppConfig):
    """Django application configuration class for Credits (Loans).

    Configures the loan application with default auto field settings.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.loan'
