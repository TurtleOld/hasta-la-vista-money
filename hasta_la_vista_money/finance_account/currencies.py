import json
from pathlib import Path
from functools import lru_cache
from django.utils.translation import get_language


@lru_cache
def _get_currencies_rates():
    path = Path(__file__).parent / 'currencies.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return {x['code_name']: x for x in data}


def currency_choices(lang: str | None = None) -> list[tuple[str, str]]:
    lang = (lang or get_language() or 'ru').lower()
    print(lang)
    use_english = lang.startswith('en')
    data = _get_currencies_rates()

    sort_field = "english_name" if use_english else "russian_name"

    return [
        (code_name, row[sort_field] if row.get(sort_field) else row.get("russian_name", code_name))
        for code_name, row in sorted(
            data.items(),
            key=lambda item: (item[1].get(sort_field) or item[1].get("russian_name") or item[0]).casefold()
        )
    ]