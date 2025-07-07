import base64
import os

from django.core.files.uploadedfile import UploadedFile
from dotenv import load_dotenv
from openai import OpenAI
from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from typing import Any, Sequence, TypeVar, Union

load_dotenv()

T = TypeVar('T')


def image_to_base64(uploaded_file) -> str:
    """
    Преобразует загруженное изображение в строку Base64.
    """
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode('utf-8')
    return f'data:image/jpeg;base64,{encoded_str}'


def analyze_image_with_ai(image_base64: UploadedFile):
    base_url = os.environ.get('API_BASE_URL', 'https://models.github.ai/inference')
    token = os.environ.get('API_KEY')
    model = os.environ.get('API_MODEL', 'openai/gpt-4o')

    client = OpenAI(
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
                    'Вы — помощник, который помогает извлекать данные с кассовых чеков. '
                    'Ваша задача — проанализировать изображение и вернуть JSON без дополнительного текста. '
                    'Извлекайте все артикулы из чека, даже если их названия повторяются или похожи. '
                    'Каждый артикул должен быть добавлен в список items как отдельный элемент. '
                    'НИКОГДА не объединяйте товары, даже если они одинаковые. '
                    'Учитывайте все строки чека, включая повторяющиеся товары.'
                ),
            },
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'text',
                        'text': (
                            'На изображении представлен кассовый чек. Преобразуйте его в JSON со следующими ключами:  '
                            '- **name_seller**: имя продавца, если указано.  '
                            '- **retail_place_address**: адрес расчетов, если указан.  '
                            '- **retail_place**: место расчетов, если указано.  '
                            '- **total_sum**: итоговая сумма в чеке.  '
                            '- **operation_type**: тип операции (1 для "Приход", 2 для "Расход").  '
                            '- **receipt_date**: дата и время в формате "ДД.ММ.ГГГГ ЧЧ:ММ", например: "20.05.2025 11:40".  '
                            '- **number_receipt**: номер ФД из чека (числовое значение).  '
                            '- **nds10**: сумма НДС 10%, если указано, или 0.  '
                            '- **nds20**: сумма НДС 20%, если указано, или 0.  '
                            '- **items**: список товаров, где каждый товар содержит:  '
                            '  - **product_name**: название товара.  '
                            '  - **category**: категория товара (определяется по названию).  '
                            '  - **price**: цена за единицу товара.  '
                            '  - **quantity**: количество товара.  '
                            '  - **amount**: общая сумма за товар (цена × количество). Нельзя пропускать товары с чека или с нулевой ценой. '
                            'Ответьте только в виде корректного JSON, без дополнительного текста. Учитывайте указания, если они присутствуют.'
                        ),
                    },
                    {
                        'type': 'text',
                        'text': (
                            'Обратите внимание: в чеке могут встречаться повторяющиеся товары с одинаковыми названиями. '
                            'Каждый такой товар должен быть добавлен в список items как отдельный элемент. '
                            'Например, если товар "Хлеб" встречается несколько раз, каждый раз он должен быть записан отдельно.'
                        ),
                    },
                    {
                        'type': 'text',
                        'text': (
                            'Пример чека:\n'
                            '1. Хлеб пшеничный 25.00 руб x 2 = 50.00\n'
                            '2. Хлеб пшеничный 25.00 руб x 1 = 25.00\n'
                            '3. Молоко 3% 45.00 руб x 1 = 45.00\n'
                            '\n'
                            'Ожидаемый JSON:\n'
                            '"items": [\n'
                            '  {"product_name": "Хлеб пшеничный", "category": "Хлебобулочные изделия", "price": 25.00, "quantity": 2, "amount": 50.00},\n'
                            '  {"product_name": "Хлеб пшеничный", "category": "Хлебобулочные изделия", "price": 25.00, "quantity": 1, "amount": 25.00},\n'
                            '  {"product_name": "Молоко 3%", "price": 45.00, "quantity": 1, "amount": 45.00}\n'
                            ']\n'
                            '\n'
                            'Каждая строка товара должна быть отдельным объектом в массиве items, даже если названия совпадают.'
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


def paginator_custom_view(
    request,
    queryset: Union[QuerySet[Any], list[Any]],
    paginate_by: int,
    page_name: str,
) -> Page[Sequence[T]]:
    """
    Кастомный пагинатор для данных.

    :param request
    :param queryset: QuerySet или список данных
    :param paginate_by: количество элементов на странице
    :param page_name: имя параметра страницы в URL
    :return Page: страница с данными
    """
    paginator = Paginator(queryset, paginate_by)
    num_page = request.GET.get(page_name)
    return paginator.get_page(num_page)
