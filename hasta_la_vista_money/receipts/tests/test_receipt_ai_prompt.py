from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from hasta_la_vista_money.receipts.services.ai_providers import (
    RateLimitExceededError,
)
from hasta_la_vista_money.receipts.services.receipt_ai_prompt import (
    check_ai_rate_limit,
)


class CheckAIRateLimitTests(TestCase):
    """Tests for local receipt inference rate limiting."""

    def setUp(self) -> None:
        cache.clear()

    def test_rate_limit_uses_atomic_increment(self) -> None:
        """Increment the same cache key for every allowed request."""
        with mock.patch(
            'hasta_la_vista_money.receipts.services.receipt_ai_prompt.config',
        ) as config_mock:
            config_mock.side_effect = lambda _name, default, cast: cast(default)

            check_ai_rate_limit(user_id=10)
            check_ai_rate_limit(user_id=10)

        self.assertEqual(cache.get('ai_rate_limit_user_10'), 2)

    def test_rate_limit_raises_after_limit(self) -> None:
        """Raise once the atomic counter exceeds the configured limit."""

        def config_side_effect(
            name: str,
            default: int,
            cast: type[int],
        ) -> int:
            if name == 'AI_RATE_LIMIT_PER_USER':
                return 1
            return cast(default)

        with mock.patch(
            'hasta_la_vista_money.receipts.services.receipt_ai_prompt.config',
            side_effect=config_side_effect,
        ):
            check_ai_rate_limit(user_id=20)
            with self.assertRaises(RateLimitExceededError):
                check_ai_rate_limit(user_id=20)

        self.assertEqual(cache.get('ai_rate_limit_user_20'), 2)
