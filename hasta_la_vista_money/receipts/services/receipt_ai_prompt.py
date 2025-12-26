"""AI prompt and utilities for extracting receipt data from images.

This module provides functions for:
- image_to_base64: encoding image file to data URL
- analyze_image_with_ai: extracting receipt data from image
- paginator_custom_view: pagination utility
"""

import base64
import importlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

import structlog
from decouple import config
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest
from openai import (
    APIError,
    APITimeoutError,
    BadRequestError,
    OpenAI as OpenAIDefault,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hasta_la_vista_money import constants

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletionSystemMessageParam,
        ChatCompletionUserMessageParam,
    )

T = TypeVar('T')

logger = structlog.get_logger(__name__)


class RateLimitExceededError(Exception):
    """Exception raised when external API rate limit is exceeded."""


class ModelUnavailableError(Exception):
    """Exception raised when AI model is unavailable."""


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
        error_msg = f'Превышен лимит запросов к OpenAI API: {count}/{limit} за {window} секунд'
        raise RateLimitExceededError(error_msg)

    cache.set(cache_key, count + 1, window)


def image_to_base64(uploaded_file: UploadedFile) -> str:
    """Encode uploaded image file to base64 data URL.

    Args:
        uploaded_file: Uploaded image file to encode.

    Returns:
        str: Data URL string with base64-encoded image.
    """
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode('utf-8')
    encoded_str = (
        encoded_str.replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
    return f'data:image/jpeg;base64,{encoded_str}'


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (ConnectionError, TimeoutError, APITimeoutError),
    ),
    reraise=True,
)
def analyze_image_with_ai(
    image_base64: UploadedFile,
    user_id: int | None = None,
) -> str:
    """Extract receipt data from image using AI.

    Uses OpenAI API to analyze receipt image and extract structured data.
    Includes retry logic for handling temporary network failures and
    rate limiting.

    Args:
        image_base64: Uploaded receipt image file.
        user_id: Optional user ID for rate limiting.

    Returns:
        str: JSON string with receipt data.

    Raises:
        RuntimeError: When image analysis errors occur.
        TypeError: If AI response doesn't contain content.
        RateLimitExceededError: If rate limit is exceeded.
    """
    check_openai_rate_limit(user_id)
    try:
        services_mod = importlib.import_module(
            'hasta_la_vista_money.receipts.services'
        )
        openai_cls = getattr(services_mod, 'OpenAI', OpenAIDefault)
    except ModuleNotFoundError:  # pragma: no cover
        openai_cls = OpenAIDefault

    base_url = str(
        config('API_BASE_URL', default='https://models.github.ai/inference')
    )
    token = str(config('API_KEY', default=''))
    model = str(config('API_MODEL', default='openai/gpt-4o'))
    base_timeout = config('OPENAI_TIMEOUT', default=120.0, cast=float)

    image_size = image_base64.size if hasattr(image_base64, 'size') else 0
    if image_size > 5 * 1024 * 1024:
        timeout = base_timeout * 2
    elif image_size > 2 * 1024 * 1024:
        timeout = base_timeout * 1.5
    else:
        timeout = base_timeout
    logger.info(
        'OpenAI API request started',
        extra={
            'model': model,
            'base_url': base_url,
            'image_size': image_size,
            'timeout': timeout,
        },
    )

    try:
        client = openai_cls(
            base_url=base_url,
            api_key=token,
            timeout=timeout,
        )

        messages: list[
            ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam
        ] = [
            cast(
                'ChatCompletionSystemMessageParam',
                {
                    'role': 'system',
                    'content': (
                        'Вы — помощник, который помогает извлекать данные с '
                        'кассовых чеков. Ваша задача — проанализировать '
                        'изображение и вернуть JSON без доп. текста. '
                        'Извлекайте все артикулы из чека, даже если названия '
                        'повторяются. Каждый артикул добавляйте в items '
                        'как отдельный элемент.'
                    ),
                },
            ),
            cast(
                'ChatCompletionUserMessageParam',
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': (
                                'На изображении представлен кассовый чек. '
                                'Преобразуйте его в JSON со след. ключами:  '
                                '- **name_seller**: имя продавца, если указано. '
                                '- **retail_place_address**: адрес расчетов, '
                                'если указан. '
                                '- **retail_place**: место расчетов, '
                                'если указано.'
                            ),
                        },
                        {
                            'type': 'text',
                            'text': (
                                '- **total_sum**: итоговая сумма в чеке. '
                                '- **operation_type**: тип операции '
                                '(1 "Приход", 2 для "Расход"). '
                                '- **receipt_date**: дата и время '
                                '"ДД.ММ.ГГГГ ЧЧ:ММ", '
                                'напр.: "20.05.2025 11:40". '
                                '- **number_receipt**: номер ФД из чека '
                                '(числовое значение). '
                                '- **nds10**: сумма НДС 10% или 0. '
                                '- **nds20**: сумма НДС 20% или 0. '
                                '- **items**: список товаров, каждый товар '
                                'содержит:  '
                                '  - **product_name**: название товара.  '
                                '  - **category**: категория товара.  '
                                '  - **price**: цена.  '
                                '  - **quantity**: количество.  '
                                '  - **amount**: сумма (цена × количество). '
                                'Нельзя пропускать товары с чека или '
                                'с нулевой ценой. Ответьте только корректным '
                                'JSON, без доп. текста.'
                            ),
                        },
                        {
                            'type': 'text',
                            'text': (
                                'Обратите внимание: повт. товары с одинаковыми '
                                'названиями нужно добавлять в items отдельными '
                                'элементами. Например, если товар "Хлеб" '
                                'встречается несколько раз, каждый раз он '
                                'должен быть записан отдельно.'
                            ),
                        },
                        {
                            'type': 'text',
                            'text': (
                                'Пример:\n'
                                '1. Хлеб пшеничный 25.00 x 2 = 50.00\n'
                                '2. Хлеб пшеничный 25.00 x 1 = 25.00\n'
                                '3. Молоко 3% 45.00 x 1 = 45.00\n'
                                '\n'
                                'Ожидаемый JSON:\n'
                                '"items": [\n'
                                '  {"product_name": "Хлеб пшеничный", '
                                '"category": "Хлебобулочные изделия", '
                                '"price": 25.00, "quantity": 2, '
                                '"amount": 50.00},\n'
                                '  {"product_name": "Хлеб пшеничный", '
                                '"category": "Хлебобулочные изделия", '
                                '"price": 25.00, "quantity": 1, '
                                '"amount": 25.00},\n'
                                '  {"product_name": "Молоко 3%", '
                                '"price": 45.00, "quantity": 1, '
                                '"amount": 45.00}\n'
                                ']\n'
                            ),
                        },
                        {
                            'type': 'image_url',
                            'image_url': {'url': image_to_base64(image_base64)},
                        },
                    ],
                },
            ),
        ]

        response = client.chat.completions.create(
            model=model,
            temperature=constants.AI_TEMPERATURE,
            messages=messages,
        )

        content = response.choices[0].message.content
        if not content:
            logger.error('OpenAI API response content is None')
            raise TypeError('AI response content is None')
        logger.info(
            'OpenAI API request completed successfully',
            extra={
                'model': model,
                'response_length': len(content),
            },
        )

    except BadRequestError as e:
        error_str = str(e)
        if 'unavailable_model' in error_str.lower() or 'unavailable model' in error_str.lower():
            logger.error(
                'OpenAI API model unavailable',
                extra={
                    'error': error_str,
                    'error_type': type(e).__name__,
                    'model': model,
                    'base_url': base_url,
                },
            )
            error_msg = (
                f'Модель {model} недоступна. '
                f'Проверьте правильность имени модели в переменной окружения API_MODEL. '
                f'Доступные модели можно проверить в документации GitHub Models API.'
            )
            raise ModelUnavailableError(error_msg) from e
        logger.exception(
            'OpenAI API bad request error',
            extra={
                'error': error_str,
                'error_type': type(e).__name__,
                'model': model,
            },
        )
        error_msg = f'Ошибка запроса к API: {error_str}'
        raise RuntimeError(error_msg) from e
    except APIError as e:
        logger.exception(
            'OpenAI API error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
        )
        error_msg = f'Ошибка API: {e!s}'
        raise RuntimeError(error_msg) from e
    except APITimeoutError as e:
        logger.error(
            'OpenAI API timeout error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
                'timeout': timeout,
                'image_size': image_size,
            },
            exc_info=True,
        )
        error_msg = f'Превышено время ожидания ответа API ({timeout} сек). Попробуйте позже или уменьшите размер изображения.'
        raise RuntimeError(error_msg) from e
    except (ConnectionError, TimeoutError) as e:
        logger.warning(
            'OpenAI API connection/timeout error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
            exc_info=True,
        )
        raise
    except (ValueError, KeyError, TypeError) as e:
        logger.exception(
            'OpenAI API data processing error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
        )
        error_msg = f'Ошибка обработки данных: {e!s}'
        raise RuntimeError(error_msg) from e
    except Exception as e:
        logger.exception(
            'OpenAI API unexpected error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
        )
        error_msg = f'Неожиданная ошибка при анализе изображения: {e!s}'
        raise RuntimeError(error_msg) from e
    else:
        return content


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
        Page: Paginated page object with items.
    """
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
