"""AI provider for receipt image analysis via OpenAI-compatible API.

Supports any provider that implements the OpenAI chat-completions API:
OpenAI, GitHub Models, Groq, OpenRouter, Azure OpenAI, Ollama, LocalAI, etc.

Configuration via environment variables:
- API_KEY: API key for the provider
- API_MODEL: Model name (e.g. gpt-4o, llama-3.1-70b)
- API_BASE_URL: Base URL of the provider endpoint
- API_TIMEOUT: Request timeout in seconds (default: 120)
"""

from __future__ import annotations

import abc
import base64
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from decouple import config
from django.utils.translation import gettext_lazy as _
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hasta_la_vista_money import constants

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = structlog.get_logger(__name__)


class RateLimitExceededError(Exception):
    """Exception raised when external API rate limit is exceeded."""


class ModelUnavailableError(Exception):
    """Exception raised when AI model is unavailable."""


def _calculate_timeout(image_size: int, base_timeout: float) -> float:
    """Calculate timeout based on image size.

    Args:
        image_size: Size of the image in bytes.
        base_timeout: Base timeout in seconds.

    Returns:
        Calculated timeout in seconds.
    """
    if image_size > 5 * 1024 * 1024:
        return base_timeout * 2
    if image_size > 2 * 1024 * 1024:
        return base_timeout * 1.5
    return base_timeout


_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_HTTP_RATE_LIMIT = 429

_SYSTEM_PROMPT = (
    'Вы — помощник, который помогает извлекать данные с '
    'кассовых чеков. Ваша задача — проанализировать '
    'изображение и вернуть JSON без доп. текста. '
    'Извлекайте все артикулы из чека, даже если названия '
    'повторяются. Каждый артикул добавляйте в items '
    'как отдельный элемент.'
)


def _build_messages(image_base64_url: str) -> list[dict[str, Any]]:
    """Build chat-completions messages for receipt analysis.

    Args:
        image_base64_url: Data URL string with base64-encoded image.

    Returns:
        List of message dicts for OpenAI-compatible API.
    """
    return [
        {
            'role': 'system',
            'content': _SYSTEM_PROMPT,
        },
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
                        '- **nds20**: сумма НДС 22% или 0. '
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
                    'image_url': {'url': image_base64_url},
                },
            ],
        },
    ]


class AIProvider(abc.ABC):
    """Abstract base class for AI receipt-analysis providers."""

    @abc.abstractmethod
    def analyze(self, uploaded_file: UploadedFile) -> str:
        """Call the provider API and return raw JSON string.

        Args:
            uploaded_file: Uploaded receipt image file.

        Returns:
            JSON string with extracted receipt data.

        Raises:
            RuntimeError: When image analysis errors occur.
            ModelUnavailableError: If the configured model is unavailable.
        """


class OpenAICompatibleProvider(AIProvider):
    """Receipt analysis via any OpenAI-compatible chat-completions API.

    Works with OpenAI, GitHub Models, Groq, OpenRouter, Azure OpenAI,
    Ollama, LocalAI, and any other provider supporting the OpenAI API format.

    Configuration via env vars:
    - API_KEY: API key
    - API_MODEL: Model name
    - API_BASE_URL: Base URL (e.g. https://api.openai.com/v1)
    - API_TIMEOUT: Timeout in seconds (default: 120)
    """

    def __init__(self) -> None:
        self._api_key = str(config('API_KEY', default=''))
        self._model = str(config('API_MODEL', default='gpt-4o'))
        self._base_url = str(
            config('API_BASE_URL', default='https://api.openai.com/v1'),
        ).rstrip('/')
        self._base_timeout = config('API_TIMEOUT', default=120.0, cast=float)

    def _encode_image(self, uploaded_file: UploadedFile) -> str:
        """Encode uploaded image file to base64 data URL.

        Args:
            uploaded_file: Uploaded image file to encode.

        Returns:
            Data URL string with base64-encoded image.
        """
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        encoded_str = base64.b64encode(file_bytes).decode('utf-8')
        return f'data:image/jpeg;base64,{encoded_str}'

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle non-2xx HTTP responses from the API.

        Args:
            response: HTTP response with error status code.

        Raises:
            ModelUnavailableError: If model is unavailable (404).
            RateLimitExceededError: If rate limit exceeded (429).
            RuntimeError: For other API errors.
        """
        status = response.status_code
        try:
            body = response.json()
            error_message = (
                body.get('error', {}).get('message', response.text)
                if isinstance(body.get('error'), dict)
                else response.text
            )
        except Exception:
            error_message = response.text

        if status == _HTTP_UNAUTHORIZED:
            logger.error(
                'API authentication error',
                extra={'status': status, 'model': self._model},
            )
            raise RuntimeError(
                str(
                    _(
                        'Ошибка аутентификации API. '
                        'Проверьте правильность ключа '
                        'в переменной окружения API_KEY.',
                    ),
                ),
            )
        if status == _HTTP_NOT_FOUND or 'unavailable' in error_message.lower():
            logger.error(
                'API model unavailable',
                extra={
                    'status': status,
                    'model': self._model,
                    'error': error_message,
                },
            )
            raise ModelUnavailableError(
                str(
                    _(
                        f'Модель {self._model} недоступна. '
                        'Проверьте правильность имени модели '
                        'в переменной окружения API_MODEL.',
                    ),
                ),
            )
        if status == _HTTP_RATE_LIMIT:
            logger.warning(
                'API rate limit exceeded',
                extra={'status': status, 'model': self._model},
            )
            raise RateLimitExceededError(
                str(_('Превышен лимит запросов к API. Попробуйте позже.')),
            )
        logger.error(
            'API error response',
            extra={
                'status': status,
                'model': self._model,
                'error': error_message,
            },
        )
        raise RuntimeError(
            str(_(f'Ошибка API (HTTP {status}): {error_message}')),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (ConnectionError, TimeoutError, httpx.TimeoutException),
        ),
        reraise=True,
    )
    def analyze(self, uploaded_file: UploadedFile) -> str:
        """Analyze receipt image using OpenAI-compatible chat-completions API.

        Args:
            uploaded_file: Uploaded receipt image file.

        Returns:
            JSON string with extracted receipt data.

        Raises:
            ModelUnavailableError: If model is unavailable.
            RateLimitExceededError: If API rate limit is exceeded.
            RuntimeError: When image analysis errors occur.
        """
        image_size = uploaded_file.size if hasattr(uploaded_file, 'size') else 0
        timeout = _calculate_timeout(image_size, self._base_timeout)
        logger.info(
            'API request started',
            extra={
                'model': self._model,
                'base_url': self._base_url,
                'image_size': image_size,
                'timeout': timeout,
            },
        )

        image_url = self._encode_image(uploaded_file)
        messages = _build_messages(image_url)
        payload = {
            'model': self._model,
            'temperature': constants.AI_TEMPERATURE,
            'messages': messages,
        }
        headers = {
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f'{self._base_url}/chat/completions',
                    json=payload,
                    headers=headers,
                )

            if not response.is_success:
                self._handle_error_response(response)

            data = response.json()
            content = data['choices'][0]['message']['content']
            if not content:
                logger.error('API response content is empty')
                raise TypeError('AI response content is empty')

        except (ModelUnavailableError, RateLimitExceededError):
            raise
        except httpx.TimeoutException as exc:
            logger.exception(
                'API timeout error',
                extra={
                    'model': self._model,
                    'timeout': timeout,
                    'image_size': image_size,
                },
            )
            raise RuntimeError(
                str(
                    _(
                        f'Превышено время ожидания ответа API ({timeout} сек). '
                        'Попробуйте позже или уменьшите размер изображения.',
                    ),
                ),
            ) from exc
        except httpx.ConnectError as exc:
            logger.warning(
                'API connection error',
                extra={'model': self._model, 'base_url': self._base_url},
                exc_info=True,
            )
            raise ConnectionError(str(exc)) from exc
        except (KeyError, IndexError, TypeError) as exc:
            logger.exception(
                'API response parsing error',
                extra={'model': self._model, 'error': str(exc)},
            )
            raise RuntimeError(
                str(_(f'Ошибка разбора ответа API: {exc!s}')),
            ) from exc
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception(
                'API unexpected error',
                extra={'model': self._model, 'error': str(exc)},
            )
            raise RuntimeError(
                str(_(f'Неожиданная ошибка при анализе изображения: {exc!s}')),
            ) from exc
        else:
            logger.info(
                'API request completed successfully',
                extra={'model': self._model, 'response_length': len(content)},
            )
            return content


def get_ai_provider() -> AIProvider:
    """Return the configured AI provider.

    Returns:
        OpenAICompatibleProvider instance.
    """
    return OpenAICompatibleProvider()
