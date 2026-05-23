"""App configuration for the transactions module."""

from django.apps import AppConfig


class TransactionsConfig(AppConfig):
    """Application config for unified transactions and categories."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hasta_la_vista_money.transactions'
    verbose_name = 'Transactions'
