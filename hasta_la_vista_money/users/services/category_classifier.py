import logging
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    'Ты помощник по категоризации финансовых операций. '
    'Пользователь даст тебе описание операции, её тип (доход/расход) '
    'и список уже существующих категорий. '
    'Верни ОДНО слово или короткую фразу — название категории. '
    'Если подходит существующая категория — используй её. '
    'Иначе придумай короткое осмысленное название. '
    'Отвечай только названием категории, без пояснений.'
)


@runtime_checkable
class CategoryClassifier(Protocol):
    """Протокол категоризатора финансовых операций."""

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        """Определить категорию для операции.

        Args:
            description: Очищенное описание операции.
            transaction_type: Тип операции — ``'income'`` или ``'expense'``.
            existing_categories: Список уже существующих категорий пользователя.

        Returns:
            Название категории (существующей или новой).
        """
        ...


class NoopClassifier:
    """Заглушка-категоризатор: возвращает описание как есть.

    Используется когда LLM не настроен — поведение совпадает с текущим
    ``get_or_create_category(description)``.
    """

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        """Вернуть описание без изменений.

        Args:
            description: Описание операции.
            transaction_type: Тип операции (не используется).
            existing_categories: Существующие категории (не используются).

        Returns:
            Исходное описание без изменений.
        """
        return description


class OpenAICompatibleClassifier:
    """Категоризатор через OpenAI-совместимый API.

    Работает с LM Studio, Ollama, Claude (через прокси), OpenAI и любым
    другим провайдером, поддерживающим ``/chat/completions``.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        """Инициализировать классификатор.

        Args:
            base_url: Базовый URL API, например ``http://localhost:1234/v1``.
            api_key: API-ключ провайдера. Может быть пустой строкой для
                локальных моделей (LM Studio, Ollama).
            model: Идентификатор модели, например ``llama-3-8b-instruct``.
        """
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._model = model

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        """Определить категорию через LLM.

        Отправляет только очищенное описание, тип операции и список категорий —
        никаких персональных данных (номера карт, счетов, имена).

        Args:
            description: Очищенное описание операции.
            transaction_type: ``'income'`` или ``'expense'``.
            existing_categories: Список категорий для приоритетного выбора.

        Returns:
            Название категории. При любой ошибке сети или парсинга возвращает
            исходное ``description``.
        """
        type_label = 'доход' if transaction_type == 'income' else 'расход'
        cats = ', '.join(existing_categories) if existing_categories else 'нет'
        user_message = (
            f'Операция: {description}\n'
            f'Тип: {type_label}\n'
            f'Существующие категории: {cats}'
        )
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'

        payload = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': 20,
            'temperature': 0,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f'{self._base_url}/chat/completions',
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data['choices'][0]['message']['content'].strip()
        except Exception:
            logger.warning(
                'category_classifier_failed',
                exc_info=True,
            )
            return description
