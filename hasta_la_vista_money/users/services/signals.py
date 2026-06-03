"""Cache-invalidation signals for statistics.

Automatically invalidates per-user statistics cache whenever a
Transaction, Receipt, or TransferMoneyLog is saved or deleted.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from hasta_la_vista_money.users.services.cache import (
    invalidate_user_detailed_statistics_cache,
)


def _invalidate_on_commit(user_id: int) -> None:
    transaction.on_commit(
        lambda: invalidate_user_detailed_statistics_cache(user_id),
    )


@receiver(post_save, sender='transactions.Transaction')
@receiver(post_delete, sender='transactions.Transaction')
def invalidate_cache_on_transaction_change(
    sender,
    instance,
    **kwargs,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='receipts.Receipt')
@receiver(post_delete, sender='receipts.Receipt')
def invalidate_cache_on_receipt_change(
    sender,
    instance,
    **kwargs,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='finance_account.TransferMoneyLog')
@receiver(post_delete, sender='finance_account.TransferMoneyLog')
def invalidate_cache_on_transfer_change(
    sender,
    instance,
    **kwargs,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='transactions.Category')
@receiver(post_delete, sender='transactions.Category')
def invalidate_cache_on_category_change(
    sender,
    instance,
    **kwargs,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='finance_account.Account')
@receiver(post_delete, sender='finance_account.Account')
def invalidate_cache_on_account_change(
    sender,
    instance,
    **kwargs,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)
