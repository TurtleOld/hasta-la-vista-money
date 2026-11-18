"""Synthetic statement identity keys and helpers for runtime tests.

Production must configure its own keyring; these values exist only inside
test modules via ``override_settings``.
"""

from django.test import override_settings

from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementFingerprint,
    StatementIdFingerprintService,
)

TEST_KEY_ONE_HEX = (
    '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f'
)
TEST_KEY_TWO_HEX = (
    '202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f'
)

TEST_STATEMENT_ID_SETTINGS = {
    'STATEMENT_ID_HMAC_KEYS': ('{"test-key-1": "' + TEST_KEY_ONE_HEX + '"}'),
    'STATEMENT_ID_HMAC_ACTIVE_KEY_ID': 'test-key-1',
}

statement_identity_settings = override_settings(**TEST_STATEMENT_ID_SETTINGS)


def fingerprint(
    bank_code: str,
    account_id: int,
    source_ref: str,
    *,
    key_id: str = 'test-key-1',
    hex_key: str = TEST_KEY_ONE_HEX,
) -> StatementFingerprint:
    """Return the fingerprint a runtime writer would store."""
    service = StatementIdFingerprintService(
        keys={key_id: bytes.fromhex(hex_key)},
        active_key_id=key_id,
    )
    return service.fingerprint(bank_code, account_id, source_ref)
