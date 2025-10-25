from typing import Any


def parse_json(
    json_data: dict[str, Any],
    key: str,
) -> list[dict[str, Any]] | int | str | None:
    """
    Модуль разбора json данных.

    Функция для разбора json данных.
    Принимает словарь и ключ для поиска значения в переданном словаре.

    :param json_data: dict
        Словарь с данными.
    :param key: str
        Ключ для поиска в словаре.
    :return: list[dict] | int | str | None
        Словарь внутри списка, либо None
    """
    if isinstance(json_data, dict):
        return _parse_dict(json_data, key)
    return None


def _parse_dict(
    data: dict[str, Any],
    key: str,
) -> list[dict[str, Any]] | int | str | None:
    for value in data.values():
        result = _parse_value(value, key)
        if result is not None:
            return result
    return data.get(key) if key in data else None


def _parse_list(
    data: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]] | int | str | None:
    if data and isinstance(data[0], dict):
        return _parse_dict(data[0], key)
    return None


def _parse_value(
    value: dict[str, Any] | list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]] | int | str | None:
    if isinstance(value, dict):
        return _parse_dict(value, key)
    if isinstance(value, list):
        return _parse_list(value, key)
    return None
