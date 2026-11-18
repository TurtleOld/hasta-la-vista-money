"""Необратимые отпечатки банковских идентификаторов строк выписки.

HMAC-SHA256 с отдельным стабильным ключом и контекстом банка/счёта
(ADR-0018). Ключи и их идентификаторы не попадают в БД, логи
и сообщения ошибок.
"""

# ruff: noqa: N818  # имя исключения зафиксировано контрактом задачи

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from hasta_la_vista_money.constants import (
    STATEMENT_ID_FINGERPRINT_VERSION,
    STATEMENT_ID_HMAC_MIN_KEY_BYTES,
)

_INVALID_CONFIG = 'Invalid statement identity HMAC configuration'


class StatementIdentityKeyUnavailable(Exception):
    """Нет пригодного ключа для вычисления отпечатка."""


@dataclass(frozen=True)
class StatementFingerprint:
    digest: str
    key_id: str
    version: int = STATEMENT_ID_FINGERPRINT_VERSION


class StatementIdFingerprintService:
    def __init__(
        self,
        keys: Mapping[str, bytes] | None = None,
        active_key_id: str | None = None,
    ) -> None:
        if keys is None:
            keys = _parse_keys_setting(
                getattr(settings, 'STATEMENT_ID_HMAC_KEYS', '') or '',
            )
            if active_key_id is None:
                active_key_id = (
                    getattr(settings, 'STATEMENT_ID_HMAC_ACTIVE_KEY_ID', '')
                    or ''
                )
        self._keys = _validate_keys(keys)
        self._active_key_id = active_key_id or ''

    def fingerprint(
        self,
        bank_code: str,
        account_id: int,
        source_ref: str,
    ) -> StatementFingerprint:
        _validate_inputs(bank_code, account_id, source_ref)
        key = self._keys.get(self._active_key_id)
        if not self._active_key_id or key is None:
            raise StatementIdentityKeyUnavailable(
                'Statement identity HMAC key is unavailable',
            )
        return StatementFingerprint(
            digest=_digest(key, bank_code, account_id, source_ref),
            key_id=self._active_key_id,
        )

    def lookup_fingerprints(
        self,
        bank_code: str,
        account_id: int,
        source_ref: str,
    ) -> tuple[StatementFingerprint, ...]:
        _validate_inputs(bank_code, account_id, source_ref)
        return tuple(
            StatementFingerprint(
                digest=_digest(key, bank_code, account_id, source_ref),
                key_id=key_id,
            )
            for key_id, key in sorted(self._keys.items())
        )

    def available_key_ids(self) -> frozenset[str]:
        return frozenset(self._keys)


def _parse_keys_setting(raw: str) -> dict[str, bytes]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ImproperlyConfigured(_INVALID_CONFIG) from None
    if not isinstance(parsed, dict):
        raise ImproperlyConfigured(_INVALID_CONFIG)
    keys: dict[str, bytes] = {}
    for key_id, hex_key in parsed.items():
        if not isinstance(hex_key, str):
            raise ImproperlyConfigured(_INVALID_CONFIG)
        try:
            keys[key_id] = bytes.fromhex(hex_key)
        except ValueError:
            raise ImproperlyConfigured(_INVALID_CONFIG) from None
    return keys


def _validate_keys(keys: Mapping[str, bytes]) -> dict[str, bytes]:
    validated = dict(keys)
    for key_id, key in validated.items():
        if (
            not isinstance(key_id, str)
            or not key_id
            or not isinstance(key, bytes)
            or len(key) < STATEMENT_ID_HMAC_MIN_KEY_BYTES
        ):
            raise ImproperlyConfigured(_INVALID_CONFIG)
    return validated


def _validate_inputs(
    bank_code: str,
    account_id: int,
    source_ref: str,
) -> None:
    if not isinstance(bank_code, str) or not bank_code.strip():
        raise ValueError('bank_code must be a non-empty string')
    if (
        not isinstance(account_id, int)
        or isinstance(account_id, bool)
        or account_id <= 0
    ):
        raise ValueError('account_id must be a positive integer')
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError('source_ref must be a non-empty string')


def _digest(
    key: bytes,
    bank_code: str,
    account_id: int,
    source_ref: str,
) -> str:
    message = json.dumps(
        [
            STATEMENT_ID_FINGERPRINT_VERSION,
            bank_code,
            account_id,
            source_ref.strip(),
        ],
        ensure_ascii=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).hexdigest()
