import re

_CARD_MASK = re.compile(r'\*\d{2,6}')
_AUTH_CODE = re.compile(r'\b\d{5,7}\b')
_DATE_FRAGMENT = re.compile(r'\b\d{2}\.\d{2}\.\d{4}\b')
_MULTI_SPACE = re.compile(r' {2,}')


def strip_pii(description: str) -> str:
    """Удалить из описания операции данные, которые не должны покидать сервер.

    Args:
        description: Сырое описание операции из банковской выписки.

    Returns:
        Очищенное описание без масок карт, кодов авторизации и дат.
    """
    result = _CARD_MASK.sub('', description)
    result = _DATE_FRAGMENT.sub('', result)
    result = _AUTH_CODE.sub('', result)
    result = _MULTI_SPACE.sub(' ', result)
    return result.strip()
