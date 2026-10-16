"""Signals for transaction-domain lifecycle actions."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from config.containers import ApplicationContainer
from hasta_la_vista_money.users.models import User


@receiver(post_save, sender=User)
def seed_system_categories_for_new_user(
    sender: type[User],
    instance: User,
    created: bool,
    raw: bool = False,
    **kwargs: object,
) -> None:
    """Give each new user the protected balance adjustment categories."""
    del sender, kwargs
    if created and not raw:
        ApplicationContainer().transactions.category_service().ensure_system_categories(
            instance,
        )
