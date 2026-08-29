from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from hasta_la_vista_money.receipts.services import (
    category_matching_evaluation as evaluation,
)
from hasta_la_vista_money.users.models import User


class Command(BaseCommand):
    """Measure per-stage hit rate on accumulated product names."""

    help = (
        'Measure how often each product category matching stage (pinned '
        'name match, writing match, semantic match) is correct on the '
        'already-categorized product rows.'
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            '--user-id',
            type=int,
            default=None,
            help='Restrict the measurement to one user.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        users = None
        user_id = options['user_id']
        if user_id is not None:
            users = User.objects.filter(pk=user_id)

        results = evaluation.evaluate_category_matching_stages(users=users)
        for result in results:
            self.stdout.write(
                f'{result.stage}: {result.hits}/{result.total} '
                f'({result.hit_rate:.1%})',
            )
