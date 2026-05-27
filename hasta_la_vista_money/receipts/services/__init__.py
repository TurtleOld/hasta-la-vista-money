from .receipt_ai_prompt import (
    analyze_image_with_ai as _analyze_image_with_ai,
)
from .receipt_ai_prompt import (
    image_to_base64 as _image_to_base64,
)

analyze_image_with_ai = _analyze_image_with_ai
image_to_base64 = _image_to_base64

__all__ = [
    'analyze_image_with_ai',
    'image_to_base64',
]
