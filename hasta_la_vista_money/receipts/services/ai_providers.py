"""AI provider implementations for receipt image analysis.

Supported providers (configured via AI_PROVIDER env var):
- openai (default): OpenAI-compatible chat-completions API
- anthropic: Anthropic Messages API (native SDK)
"""

from __future__ import annotations

import abc
import base64
from typing import TYPE_CHECKING, Any, cast

import anthropic
import structlog
from decouple import config
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
from openai import (
    APIError,
    APITimeoutError,
    BadRequestError,
)
from openai import OpenAI as _OpenAI
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


def _create_openai_messages(
    image_base64_url: str,
) -> list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam]:
    """Create messages for receipt analysis via OpenAI chat-completions API.

    Args:
        image_base64_url: Data URL string with base64-encoded image.

    Returns:
        List of message parameters for OpenAI API.
    """
    return [
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
                        'image_url': {'url': image_base64_url},
                    },
                ],
            },
        ),
    ]


def _create_anthropic_messages(b64_data: str) -> list[dict[str, Any]]:
    """Create messages for receipt analysis via Anthropic Messages API.

    Args:
        b64_data: Raw base64-encoded image data (no data: URL prefix).

    Returns:
        List of message dicts for Anthropic API.
    """
    return [
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
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/jpeg',
                        'data': b64_data,
                    },
                },
            ],
        },
    ]


_ANTHROPIC_SYSTEM_PROMPT = (
    'Вы — помощник, который помогает извлекать данные с '
    'кассовых чеков. Ваша задача — проанализировать '
    'изображение и вернуть JSON без доп. текста. '
    'Извлекайте все артикулы из чека, даже если названия '
    'повторяются. Каждый артикул добавляйте в items '
    'как отдельный элемент.'
)


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


class OpenAIProvider(AIProvider):
    """Receipt analysis via OpenAI-compatible chat-completions API.

    Configuration via env vars: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL.
    Falls back to legacy API_KEY, API_BASE_URL, API_MODEL if new vars not set.
    """

    def __init__(self) -> None:
        self._base_url = str(
            config(
                'OPENAI_BASE_URL',
                default=config(
                    'API_BASE_URL',
                    default='https://models.github.ai/inference',
                ),
            ),
        )
        self._token = str(
            config(
                'OPENAI_API_KEY',
                default=config('API_KEY', default=''),
            ),
        )
        self._model = str(
            config(
                'OPENAI_MODEL',
                default=config('API_MODEL', default='openai/gpt-4o'),
            ),
        )
        self._base_timeout = config('OPENAI_TIMEOUT', default=120.0, cast=float)

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
        encoded_str = (
            encoded_str.replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )
        return f'data:image/jpeg;base64,{encoded_str}'

    def _handle_bad_request(self, exc: BadRequestError) -> None:
        """Handle BadRequestError from OpenAI API.

        Args:
            exc: BadRequestError exception.

        Raises:
            ModelUnavailableError: If model is unavailable.
            RuntimeError: For other bad request errors.
        """
        error_str = str(exc)
        if (
            'unavailable_model' in error_str.lower()
            or 'unavailable model' in error_str.lower()
        ):
            logger.exception(
                'OpenAI API model unavailable',
                extra={
                    'error': error_str,
                    'error_type': type(exc).__name__,
                    'model': self._model,
                    'base_url': self._base_url,
                },
            )
            error_msg = str(
                _(
                    f'Модель {self._model} недоступна. '
                    'Проверьте правильность имени модели '
                    'в переменной окружения OPENAI_MODEL. '
                    'Доступные модели можно проверить '
                    'в документации GitHub Models API.',
                ),
            )
            raise ModelUnavailableError(error_msg) from exc

        logger.exception(
            'OpenAI API bad request error',
            extra={
                'error': error_str,
                'error_type': type(exc).__name__,
                'model': self._model,
            },
        )
        error_msg = str(_(f'Ошибка запроса к API: {error_str}'))
        raise RuntimeError(error_msg) from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (ConnectionError, TimeoutError, APITimeoutError),
        ),
        reraise=True,
    )
    def analyze(self, uploaded_file: UploadedFile) -> str:
        """Analyze receipt image using OpenAI API.

        Args:
            uploaded_file: Uploaded receipt image file.

        Returns:
            JSON string with extracted receipt data.

        Raises:
            ModelUnavailableError: If model is unavailable.
            RuntimeError: When image analysis errors occur.
        """
        image_size = uploaded_file.size if hasattr(uploaded_file, 'size') else 0
        timeout = _calculate_timeout(image_size, self._base_timeout)
        logger.info(
            'OpenAI API request started',
            extra={
                'model': self._model,
                'base_url': self._base_url,
                'image_size': image_size,
                'timeout': timeout,
            },
        )

        try:
            client = _OpenAI(
                base_url=self._base_url,
                api_key=self._token,
                timeout=timeout,
            )
            image_url = self._encode_image(uploaded_file)
            messages = _create_openai_messages(image_url)
            response = client.chat.completions.create(
                model=self._model,
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
                    'model': self._model,
                    'response_length': len(content),
                },
            )
        except BadRequestError as exc:
            self._handle_bad_request(exc)
            raise
        except APITimeoutError as exc:
            logger.exception(
                'OpenAI API timeout error',
                extra={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                    'model': self._model,
                    'timeout': timeout,
                    'image_size': image_size,
                },
            )
            error_msg = str(
                _(
                    f'Превышено время ожидания ответа API ({timeout} сек). '
                    'Попробуйте позже или уменьшите размер изображения.',
                ),
            )
            raise RuntimeError(error_msg) from exc
        except APIError as exc:
            logger.exception(
                'OpenAI API error',
                extra={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                    'model': self._model,
                },
            )
            error_msg = str(_(f'Ошибка API: {exc!s}'))
            raise RuntimeError(error_msg) from exc
        except (ConnectionError, TimeoutError) as exc:
            logger.warning(
                'OpenAI API connection/timeout error',
                extra={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                    'model': self._model,
                },
                exc_info=True,
            )
            raise
        except (ValueError, KeyError, TypeError) as exc:
            logger.exception(
                'OpenAI API data processing error',
                extra={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                    'model': self._model,
                },
            )
            error_msg = str(_(f'Ошибка обработки данных: {exc!s}'))
            raise RuntimeError(error_msg) from exc
        except Exception as exc:
            logger.exception(
                'OpenAI API unexpected error',
                extra={
                    'error': str(exc),
                    'error_type': type(exc).__name__,
                    'model': self._model,
                },
            )
            error_msg = str(
                _(f'Неожиданная ошибка при анализе изображения: {exc!s}'),
            )
            raise RuntimeError(error_msg) from exc
        else:
            return content


class AnthropicProvider(AIProvider):
    """Receipt analysis via Anthropic Messages API (native SDK).

    Configuration via env vars: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL. Image transmitted as raw base64 source block
    (no data: URL prefix, no HTML-escape).
    System prompt passed as separate parameter.
    """

    def __init__(self) -> None:
        self._token = str(config('ANTHROPIC_API_KEY', default=''))
        self._base_url = str(
            config('ANTHROPIC_BASE_URL', default='https://api.anthropic.com'),
        )
        self._model = str(
            config('ANTHROPIC_MODEL', default='claude-opus-4-6'),
        )
        self._base_timeout = config('OPENAI_TIMEOUT', default=120.0, cast=float)

    def _handle_error(
        self,
        exc: BaseException,
        timeout: float,
        image_size: int,
    ) -> None:
        """Handle Anthropic API errors and raise appropriate exceptions.

        Args:
            exc: The caught exception.
            timeout: Request timeout used.
            image_size: Size of the image in bytes.

        Raises:
            ModelUnavailableError: If the model is unavailable.
            RuntimeError: For all other API errors.
        """
        if isinstance(exc, anthropic.AuthenticationError):
            logger.exception(
                'Anthropic API authentication error',
                extra={'error': str(exc), 'model': self._model},
            )
            raise RuntimeError(
                str(
                    _(
                        'Ошибка аутентификации Anthropic API. '
                        'Проверьте правильность ключа '
                        'в переменной окружения ANTHROPIC_API_KEY.',
                    ),
                ),
            ) from exc
        if isinstance(exc, anthropic.BadRequestError):
            error_str = str(exc)
            if (
                'unavailable_model' in error_str.lower()
                or 'unavailable model' in error_str.lower()
            ):
                logger.exception(
                    'Anthropic API model unavailable',
                    extra={'error': error_str, 'model': self._model},
                )
                raise ModelUnavailableError(
                    str(
                        _(
                            f'Модель {self._model} недоступна. '
                            'Проверьте правильность имени модели '
                            'в переменной окружения ANTHROPIC_MODEL.',
                        ),
                    ),
                ) from exc
            logger.exception(
                'Anthropic API bad request error',
                extra={'error': error_str, 'model': self._model},
            )
            raise RuntimeError(
                str(_(f'Ошибка запроса к API: {error_str}')),
            ) from exc
        if isinstance(exc, anthropic.APITimeoutError):
            logger.exception(
                'Anthropic API timeout error',
                extra={
                    'error': str(exc),
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
        if isinstance(exc, TypeError):
            error_str = str(exc)
            if 'authentication method' in error_str or 'api_key' in error_str:
                logger.exception(
                    'Anthropic API authentication configuration error',
                    extra={'error': error_str, 'model': self._model},
                )
                raise RuntimeError(
                    str(
                        _(
                            'Ошибка аутентификации Anthropic API. '
                            'Проверьте правильность ключа '
                            'в переменной окружения ANTHROPIC_API_KEY.',
                        ),
                    ),
                ) from exc
            logger.exception(
                'Anthropic API data processing error',
                extra={
                    'error': error_str,
                    'error_type': type(exc).__name__,
                    'model': self._model,
                },
            )
            raise RuntimeError(
                str(_(f'Ошибка обработки данных: {error_str}')),
            ) from exc
        logger.exception(
            'Anthropic API error',
            extra={
                'error': str(exc),
                'error_type': type(exc).__name__,
                'model': self._model,
            },
        )
        raise RuntimeError(
            str(_(f'Ошибка API: {exc!s}')),
        ) from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (ConnectionError, TimeoutError, anthropic.APIConnectionError),
        ),
        reraise=True,
    )
    def analyze(self, uploaded_file: UploadedFile) -> str:
        """Analyze receipt image using Anthropic API.

        Args:
            uploaded_file: Uploaded receipt image file.

        Returns:
            JSON string with extracted receipt data.

        Raises:
            ModelUnavailableError: If model is unavailable.
            RuntimeError: When image analysis errors occur.
        """
        image_size = uploaded_file.size if hasattr(uploaded_file, 'size') else 0
        timeout = _calculate_timeout(image_size, self._base_timeout)
        logger.info(
            'Anthropic API request started',
            extra={
                'model': self._model,
                'base_url': self._base_url,
                'image_size': image_size,
                'timeout': timeout,
            },
        )
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()
        b64_data = base64.b64encode(raw_bytes).decode('utf-8')
        try:
            client = anthropic.Anthropic(
                api_key=self._token,
                base_url=self._base_url,
                timeout=timeout,
            )
            messages = _create_anthropic_messages(b64_data)
            response = client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=_ANTHROPIC_SYSTEM_PROMPT,
                messages=messages,
            )
            content = response.content[0].text if response.content else ''
            if not content:
                logger.error('Anthropic API response content is empty')
                raise TypeError('Anthropic response content is empty')
            logger.info(
                'Anthropic API request completed successfully',
                extra={
                    'model': self._model,
                    'response_length': len(content),
                },
            )
        except anthropic.APIConnectionError:
            logger.warning(
                'Anthropic API connection error',
                extra={'model': self._model},
                exc_info=True,
            )
            raise
        except (
            anthropic.AuthenticationError,
            anthropic.BadRequestError,
            anthropic.APITimeoutError,
            anthropic.APIError,
            TypeError,
            ValueError,
            KeyError,
            Exception,
        ) as exc:
            self._handle_error(exc, timeout, image_size)
        else:
            return content
        return ''


def get_ai_provider() -> AIProvider:
    """Return the configured AI provider based on AI_PROVIDER env var.

    Returns:
        AnthropicProvider if AI_PROVIDER=anthropic, else OpenAIProvider.
    """
    provider_name = str(config('AI_PROVIDER', default='openai')).lower().strip()
    if provider_name == 'anthropic':
        return AnthropicProvider()
    return OpenAIProvider()
