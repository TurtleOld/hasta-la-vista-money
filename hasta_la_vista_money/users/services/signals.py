"""Cache-invalidation signals for statistics.

Invalidates the statistics cache of the record owner and of everyone who
reads their data through a group whenever statistics inputs change.
"""

from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from hasta_la_vista_money.budget.models import Budget, Planning
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import FamilyGroupMembership
from hasta_la_vista_money.users.services.cache import (
    invalidate_group_statistics_cache,
    invalidate_user_circle_statistics_cache,
)


def _invalidate_on_commit(user_id: int) -> None:
    transaction.on_commit(
        lambda: invalidate_user_circle_statistics_cache(user_id),
    )


@receiver(post_save, sender='transactions.Transaction')
@receiver(post_delete, sender='transactions.Transaction')
def invalidate_cache_on_transaction_change(
    sender: type[Model],
    instance: Transaction,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='receipts.Receipt')
@receiver(post_delete, sender='receipts.Receipt')
def invalidate_cache_on_receipt_change(
    sender: type[Model],
    instance: Receipt,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='finance_account.TransferMoneyLog')
@receiver(post_delete, sender='finance_account.TransferMoneyLog')
def invalidate_cache_on_transfer_change(
    sender: type[Model],
    instance: TransferMoneyLog,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='transactions.Category')
@receiver(post_delete, sender='transactions.Category')
def invalidate_cache_on_category_change(
    sender: type[Model],
    instance: Category,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='finance_account.Account')
@receiver(post_delete, sender='finance_account.Account')
def invalidate_cache_on_account_change(
    sender: type[Model],
    instance: Account,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='budget.Budget')
@receiver(post_delete, sender='budget.Budget')
def invalidate_cache_on_budget_change(
    sender: type[Model],
    instance: Budget,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='budget.Planning')
@receiver(post_delete, sender='budget.Planning')
def invalidate_cache_on_planning_change(
    sender: type[Model],
    instance: Planning,
    **kwargs: object,
) -> None:
    del sender, kwargs
    _invalidate_on_commit(instance.user_id)


@receiver(post_save, sender='users.FamilyGroupMembership')
@receiver(post_delete, sender='users.FamilyGroupMembership')
def invalidate_cache_on_membership_change(
    sender: type[Model],
    instance: FamilyGroupMembership,
    **kwargs: object,
) -> None:
    del sender, kwargs
    group_id, user_id = instance.group_id, instance.user_id
    transaction.on_commit(
        lambda: invalidate_group_statistics_cache(group_id, user_id),
    )
