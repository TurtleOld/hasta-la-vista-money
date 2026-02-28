"""AI prompt and utilities for extracting receipt data from images.

This module provides functions for:
- image_to_base64: encoding image file to data URL
- analyze_image_with_ai: extracting receipt data from image using configured AI provider
- paginator_custom_view: pagination utility
"""

import base64
from collections.abc import Sequence
from typing import Any, TypeVar

import structlog
from decouple import config
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.receipts.services.ai_providers import (
    ModelUnavailableError,
    RateLimitExceededError,
    get_ai_provider,
)

T = TypeVar('T')

logger = structlog.get_logger(__name__)

__all__ = [
    'ModelUnavailableError',
    'RateLimitExceededError',
    'analyze_image_with_ai',
    'image_to_base64',
    'paginator_custom_view',
]


def check_openai_rate_limit(user_id: int | None = None) -> None:
    """Check OpenAI API rate limit.

    Args:
        user_id: User ID for rate limiting. If None, uses global limit.

    Raises:
        RateLimitExceededError: If rate limit is exceeded.
    """
    if user_id is not None:
        cache_key = f'openai_rate_limit_user_{user_id}'
        limit = config('OPENAI_RATE_LIMIT_PER_USER', default=10, cast=int)
    else:
        cache_key = 'openai_rate_limit_global'
        limit = config('OPENAI_RATE_LIMIT_GLOBAL', default=100, cast=int)

    window = config('OPENAI_RATE_LIMIT_WINDOW', default=60, cast=int)

    count = cache.get(cache_key, 0)
    if count >= limit:
        logger.warning(
            'OpenAI API rate limit exceeded',
            extra={
                'user_id': user_id,
                'count': count,
                'limit': limit,
                'window': window,
            },
        )
        error_msg = str(
            _(
                'Превышен лимит запросов к OpenAI API: '
                f'{count}/{limit} за {window} секунд',
            ),
        )
        raise RateLimitExceededError(error_msg)

    cache.set(cache_key, count + 1, window)


def image_to_base64(uploaded_file: UploadedFile) -> str:
    """Encode uploaded image file to base64 data URL.

    Args:
        uploaded_file: Uploaded image file to encode.

    Returns:
        Data URL string with base64-encoded image.
    """
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode('utf-8')
    encoded_str = (
        encoded_str.replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
    return f'data:image/jpeg;base64,{encoded_str}'


def analyze_image_with_ai(
    image_base64: UploadedFile,
    user_id: int | None = None,
) -> str:
    """Extract receipt data from image using configured AI provider.

    The provider is selected via AI_PROVIDER env var ('openai' or 'anthropic').
    Includes rate limiting and retry logic delegated to the provider.

    Args:
        image_base64: Uploaded receipt image file.
        user_id: Optional user ID for rate limiting.

    Returns:
        JSON string with receipt data.

    Raises:
        RateLimitExceededError: If rate limit is exceeded.
        ModelUnavailableError: If the configured model is unavailable.
        RuntimeError: When image analysis errors occur.
        TypeError: If AI response doesn't contain content.
    """
    check_openai_rate_limit(user_id)
    provider = get_ai_provider()
    return provider.analyze(image_base64)


def paginator_custom_view(
    request: HttpRequest,
    queryset: QuerySet[Any] | list[Any],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[Any]]:
    """Paginate queryset or list with custom page parameter name.

    Args:
        request: HTTP request object with GET parameters.
        queryset: QuerySet or list to paginate.
        paginate_by: Number of items per page.
        page_name: Name of the GET parameter for page number.

    Returns:
        Paginated page object with items.
    """
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
