from openai import OpenAI as _OpenAI

from .receipt_ai_prompt import (
    analyze_image_with_ai as _analyze_image_with_ai,
)
from .receipt_ai_prompt import (
    image_to_base64 as _image_to_base64,
)
from .receipt_ai_prompt import (
    paginator_custom_view as _paginator_custom_view,
)

# Re-export legacy functions expected at
# `hasta_la_vista_money.receipts.services`
analyze_image_with_ai = _analyze_image_with_ai
image_to_base64 = _image_to_base64
paginator_custom_view = _paginator_custom_view
OpenAI = _OpenAI

__all__ = [
    'OpenAI',
    'analyze_image_with_ai',
    'image_to_base64',
    'paginator_custom_view',
]
