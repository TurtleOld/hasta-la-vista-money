"""Signals for receipt-domain lifecycle actions."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from config.containers import ApplicationContainer
from hasta_la_vista_money.users.models import User


@receiver(post_save, sender=User)
def seed_product_categories_for_new_user(
    sender: type[User],
    instance: User,
    created: bool,
    **kwargs: object,
) -> None:
    """Give each new account the standard product category directory."""
    del sender, kwargs
    if created:
        ApplicationContainer().receipts.product_category_service().seed_starter_product_categories(
            instance,
        )
