"""HMAC identities for bank statement operations.

A statement identifier is only a hint. The technical identity of an observed
operation is an HMAC-SHA256 over the bank context, the account, the bank
identifier and the fingerprint format version. The active key is used for
writing; every configured key is used for recognition so a planned rotation
keeps old fingerprints readable. A missing configuration or a lost key is an
explicit, safe failure: callers must not auto-post or conclude that an
operation does not exist.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings


class StatementFingerprintUnavailableError(ValueError):
    """Raised when a safe statement fingerprint cannot be computed."""


@dataclass(frozen=True)
class StatementFingerprint:
    """One HMAC fingerprint and the versions that produced it."""

    digest: str
    key_version: str
    format_version: int


def _configured_keys() -> dict[str, str]:
    raw: Any = getattr(settings, 'STATEMENT_FINGERPRINT_KEYS', {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): str(secret)
        for key, secret in raw.items()
        if str(key) and str(secret)
    }


class StatementIdentityService:
    """Compute and recognize statement fingerprints from a keyring."""

    def __init__(
        self,
        *,
        keys: Mapping[str, str] | None = None,
        active_key_version: str | None = None,
        format_version: int | None = None,
    ) -> None:
        self._keys = dict(keys) if keys is not None else _configured_keys()
        self._active_key_version = (
            active_key_version
            if active_key_version is not None
            else str(
                getattr(settings, 'STATEMENT_FINGERPRINT_ACTIVE_KEY', ''),
            )
        )
        self._format_version = (
            format_version
            if format_version is not None
            else int(
                getattr(settings, 'STATEMENT_FINGERPRINT_FORMAT_VERSION', 1),
            )
        )

    @property
    def is_configured(self) -> bool:
        """Return whether an active key is available for writing."""
        return bool(
            self._active_key_version
            and self._keys.get(self._active_key_version),
        )

    def fingerprint(
        self,
        *,
        bank: str,
        account_id: int,
        source_ref: str | None,
        key_version: str | None = None,
    ) -> StatementFingerprint:
        """Return the fingerprint written with the active or chosen key.

        Raises:
            StatementFingerprintUnavailableError: The keyring is not
                configured, the chosen key is unknown, or the bank
                identifier is empty.
        """
        if not source_ref:
            raise StatementFingerprintUnavailableError('source_ref')
        version = key_version or self._active_key_version
        secret = self._keys.get(version)
        if not version or not secret:
            raise StatementFingerprintUnavailableError(version or 'key')
        message = '|'.join(
            (
                str(self._format_version),
                str(bank),
                str(account_id),
                source_ref,
            ),
        )
        digest = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return StatementFingerprint(
            digest=digest,
            key_version=version,
            format_version=self._format_version,
        )

    def recognition(
        self,
        *,
        bank: str,
        account_id: int,
        source_ref: str | None,
    ) -> list[StatementFingerprint]:
        """Return fingerprints under every configured key for lookup.

        The active key is listed first; old keys remain readable during a
        planned rotation. A lost key is not silently substituted.
        """
        if not source_ref:
            return []
        versions = list(self._keys)
        if self._active_key_version in versions:
            versions.remove(self._active_key_version)
            versions.insert(0, self._active_key_version)
        return [
            self.fingerprint(
                bank=bank,
                account_id=account_id,
                source_ref=source_ref,
                key_version=version,
            )
            for version in versions
        ]

    def missing_keys(self, stored_versions: Iterable[str]) -> set[str]:
        """Return stored key versions that this keyring cannot resolve."""
        return {
            version
            for version in stored_versions
            if version and version not in self._keys
        }

    def incompatible_format_versions(
        self,
        stored_versions: Iterable[int],
    ) -> set[int]:
        """Return stored fingerprint formats this code cannot recognize."""
        return {
            version
            for version in stored_versions
            if version and version != self._format_version
        }
