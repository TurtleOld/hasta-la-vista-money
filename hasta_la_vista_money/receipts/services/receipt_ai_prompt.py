"""AI prompt and utilities for extracting receipt data from images.

Публичные функции:
- image_to_base64: кодирование файла-изображения в data URL
- analyze_image_with_ai: извлечение данных чека из изображения
- paginator_custom_view: утилита пагинации
"""

import base64
import importlib
import logging
from collections.abc import Sequence
from typing import Any, TypeVar, cast

import structlog
from decouple import config
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest
from openai import OpenAI as OpenAIDefault
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hasta_la_vista_money import constants

T = TypeVar('T')

logger = structlog.get_logger(__name__)


class RateLimitExceeded(Exception):
    """Исключение при превышении лимита запросов к внешнему API."""

    pass


def check_openai_rate_limit(user_id: int | None = None) -> None:
    """Проверить лимит запросов к OpenAI API.

    Args:
        user_id: ID пользователя для rate limiting. Если None, используется
                 общий лимит.

    Raises:
        RateLimitExceeded: Если лимит превышен.
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
        raise RateLimitExceeded(
            f'Превышен лимит запросов к OpenAI API: {count}/{limit} за {window} секунд'
        )

    cache.set(cache_key, count + 1, window)


def image_to_base64(uploaded_file: UploadedFile) -> str:
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
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def analyze_image_with_ai(
    image_base64: UploadedFile,
    user_id: int | None = None,
) -> str:
    """Извлечь данные чека из изображения с помощью AI.

    Использует OpenAI API для анализа изображения чека и извлечения
    структурированных данных. Включает retry логику для обработки
    временных сбоев сети и rate limiting.

    Args:
        image_base64: Загруженный файл изображения чека
        user_id: Опциональный ID пользователя для rate limiting

    Returns:
        Строка с JSON данными чека

    Raises:
        RuntimeError: При ошибках анализа изображения
        TypeError: Если ответ AI не содержит контента
        RateLimitExceeded: Если превышен лимит запросов
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
    timeout = config('OPENAI_TIMEOUT', default=30.0, cast=float)

    image_size = image_base64.size if hasattr(image_base64, 'size') else 0
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
                ChatCompletionSystemMessageParam,
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
                ChatCompletionUserMessageParam,
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

        return content

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
        logger.error(
            'OpenAI API data processing error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
            exc_info=True,
        )
        error_msg = f'Ошибка при анализе изображения: {e!s}'
        raise RuntimeError(error_msg) from e
    except Exception as e:
        logger.error(
            'OpenAI API unexpected error',
            extra={
                'error': str(e),
                'error_type': type(e).__name__,
                'model': model,
            },
            exc_info=True,
        )
        error_msg = f'Неожиданная ошибка при анализе изображения: {e!s}'
        raise RuntimeError(error_msg) from e


def paginator_custom_view(
    request: HttpRequest,
    queryset: QuerySet[Any] | list[Any],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[Any]]:
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
