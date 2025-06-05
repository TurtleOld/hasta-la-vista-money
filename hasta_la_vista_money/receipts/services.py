import os
from openai import OpenAI
import base64
from django.core.files.uploadedfile import UploadedFile


def image_to_base64(uploaded_file) -> str:
    """
    Преобразует загруженное изображение в строку Base64.
    """
    file_bytes = uploaded_file.read()
    encoded_str = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded_str}"



def analyze_image_with_ai(image_base64: UploadedFile):
    token = os.getenv('GITHUB_TOKEN')
    endpoint = "https://models.github.ai/inference"
    model = os.getenv('MODEL')

    client = OpenAI(
        base_url=endpoint,
        api_key=token,
    )

    response = client.chat.completions.create(
        model=model,
        temperature=1.0,
        top_p=1.0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Вы — помощник, который помогает извлекать данные с кассовых чеков. "
                    "Ваша задача — проанализировать изображение и вернуть JSON без дополнительного текста."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            'На изображении представлен кассовый чек. '
                            'Преобразуйте его в JSON с ключами: '
                            'name_seller (имя продавца), retail_place_address (адрес расчетов), '
                            'retail_place (место расчетов), total_sum (итоговая сумма), '
                            'operation_type (Приход - 1, Расход - 2)'
                            'receipt_date (дата и время, формат d.m.Y H:M), number_receipt (ФД на чеке, числовое значение), '
                            'Может содержать НДС 10% и 20%, поля nds10 и nds20 соответственно'
                            'items — список товаров. Каждый товар содержит: product_name, category, price, quantity, amount. '
                            'Категорию определяйте по названию товара.'
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_to_base64(image_base64)
                        }
                    }
                ]
            }
        ]
    )

    return response.choices[0].message.content