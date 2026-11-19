from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from core.services.external_model import ExternalModelTransport

logger = structlog.get_logger(__name__)

#: Category name that means "the local rules did not recognise this row".
FALLBACK_CATEGORY: Final = 'Без категории'

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


class LocalCategoryClassifier:
    """Deterministic local category rules for bank statement rows.

    Only an existing user category named in the operation description is an
    explicit local category. Everything else stays unknown and is sent to
    manual markup. This implementation never performs a network request and
    never invents a category.
    """

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        """Return an existing matching category or the fallback marker."""
        del transaction_type
        normalized = _normalize_category_text(description)
        if not normalized:
            return FALLBACK_CATEGORY
        for category in sorted(
            existing_categories,
            key=lambda name: (-len(name), name),
        ):
            candidate = _normalize_category_text(category)
            if candidate and _contains_category(normalized, candidate):
                return category
        return FALLBACK_CATEGORY


def _normalize_category_text(text: str) -> str:
    """Casefold and collapse separators without changing word boundaries."""
    return re.sub(r'\s+', ' ', str(text).casefold()).strip(' .,;:-')


def _contains_category(text: str, category: str) -> bool:
    """Match a category as whole words inside the operation description."""
    pattern = rf'(?<!\w){re.escape(category)}(?!\w)'
    return re.search(pattern, text) is not None


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


class ExternalModelCategoryClassifier:
    """Категоризатор финансовых операций через внешнюю модель."""

    def __init__(self, *, transport: ExternalModelTransport) -> None:
        """Инициализировать классификатор.

        Args:
            transport: Общий транспорт внешней модели.
        """
        self._transport = transport

    def classify(
        self,
        description: str,
        transaction_type: str,
        existing_categories: list[str],
    ) -> str:
        """Определить категорию через внешнюю модель.

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
        try:
            data = self._transport.complete(
                messages=[
                    {'role': 'system', 'content': _SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_message},
                ],
                max_tokens=20,
                temperature=0,
            )
            content = data['choices'][0]['message']['content']
            return str(content).strip()
        except Exception:
            logger.warning(
                'category_classifier_failed',
                exc_info=True,
            )
            return description
