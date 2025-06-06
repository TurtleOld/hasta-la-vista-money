import os
from openai import OpenAI
import base64
from django.core.files.uploadedfile import UploadedFile


def image_to_base64(uploaded_file) -> str:
    """
    Преобразует загруженное изображение в строку Base64.
    """
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode('utf-8')
    return f'data:image/jpeg;base64,{encoded_str}'


def analyze_image_with_ai(image_base64: UploadedFile):
    token = os.getenv('GITHUB_TOKEN')
    endpoint = 'https://models.github.ai/inference'
    model = os.getenv('MODEL')

    client = OpenAI(
        base_url=endpoint,
        api_key=token,
    )

    response = client.chat.completions.create(
        model=model,
        temperature=1.0,
        top_p=0.4,
        messages=[
            {
                'role': 'system',
                'content': (
                    'Вы — помощник, который помогает извлекать данные с кассовых чеков. '
                    'Ваша задача — проанализировать изображение и вернуть JSON без дополнительного текста.'
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "На изображении представлен кассовый чек. Преобразуйте его в JSON со следующими ключами:  "
                            "- **name_seller**: имя продавца, если указано.  "
                            "- **retail_place_address**: адрес расчетов, если указан.  "
                            "- **retail_place**: место расчетов, если указано.  "
                            "- **total_sum**: итоговая сумма в чеке.  "
                            "- **operation_type**: тип операции (1 для \"Приход\", 2 для \"Расход\").  "
                            "- **receipt_date**: дата и время в формате \"ДД.ММ.ГГГГ ЧЧ:ММ\", например: \"20.05.2025 11:40\".  "
                            "- **number_receipt**: номер ФД из чека (числовое значение).  "
                            "- **nds10**: сумма НДС 10%, если указано, или 0.  "
                            "- **nds20**: сумма НДС 20%, если указано, или 0.  "
                            "- **items**: список товаров, где каждый товар содержит:  "
                            "  - **product_name**: название товара.  "
                            "  - **category**: категория товара (определяется по названию).  "
                            "  - **price**: цена за единицу товара.  "
                            "  - **quantity**: количество товара.  "
                            "  - **amount**: общая сумма за товар (цена × количество).  "
                            "Ответьте только в виде корректного JSON, без дополнительного текста. Учитывайте указания, если они присутствуют."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_base64(image_base64)},
                    },
                ],
            },
        ],
    )

    return response.choices[0].message.content
