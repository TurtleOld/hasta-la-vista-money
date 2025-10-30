"""AI prompt and utilities for extracting receipt data from images.

Публичные функции:
- image_to_base64: кодирование файла-изображения в data URL
- analyze_image_with_ai: извлечение данных чека из изображения
- paginator_custom_view: утилита пагинации
"""

import base64
import importlib
from collections.abc import Sequence
from typing import Any, TypeVar

from decouple import config
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from openai import OpenAI as OpenAIDefault

T = TypeVar('T')


def image_to_base64(uploaded_file) -> str:
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode('utf-8')
    encoded_str = (
        encoded_str.replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
    return f'data:image/jpeg;base64,{encoded_str}'


def analyze_image_with_ai(image_base64: UploadedFile):
    # Allow tests to patch `hasta_la_vista_money.receipts.services.OpenAI`.
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

    try:
        client = openai_cls(
            base_url=base_url,
            api_key=token,
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0.6,
            messages=[
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
            ],
        )
        return response.choices[0].message.content
    except (
        ConnectionError,
        TimeoutError,
        ValueError,
        KeyError,
        Exception,
    ) as e:
        error_msg = f'Ошибка при анализе изображения: {e!s}'
        raise RuntimeError(error_msg) from e


def paginator_custom_view(
    request,
    queryset: QuerySet[Any] | list[Any],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[T]]:
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
