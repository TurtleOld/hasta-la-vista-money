import json

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementFingerprint,
    StatementIdentityKeyUnavailable,
    StatementIdFingerprintService,
)

KEY_ONE_HEX = '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f'
KEY_TWO_HEX = '202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f'
KEY_ONE = bytes.fromhex(KEY_ONE_HEX)
KEY_TWO = bytes.fromhex(KEY_TWO_HEX)


class StatementIdFingerprintServiceTest(SimpleTestCase):
    def test_known_digest_vector(self) -> None:
        service = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )
        fingerprint = service.fingerprint('sberbank', 42, 'op-123')
        self.assertEqual(
            fingerprint,
            StatementFingerprint(
                digest=(
                    '7b9f67b50155d71fc7d3d9b5ca4872c8e24eed548af1b38b'
                    '574f05a33a211fbe'
                ),
                key_id='test-key-1',
                version=1,
            ),
        )

    def test_determinism(self) -> None:
        first = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )
        second = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )
        self.assertEqual(
            first.fingerprint('sberbank', 42, 'op-123'),
            first.fingerprint('sberbank', 42, 'op-123'),
        )
        self.assertEqual(
            first.fingerprint('sberbank', 42, 'op-123'),
            second.fingerprint('sberbank', 42, 'op-123'),
        )


class StatementIdFingerprintValidationTest(SimpleTestCase):
    def setUp(self) -> None:
        self.service = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )

    def test_bank_account_separation(self) -> None:
        base = self.service.fingerprint('sberbank', 42, 'op-123')
        self.assertNotEqual(
            base,
            self.service.fingerprint('raiffeisen', 42, 'op-123'),
        )
        self.assertNotEqual(
            base,
            self.service.fingerprint('sberbank', 43, 'op-123'),
        )
        self.assertNotEqual(
            base,
            self.service.fingerprint('sberbank', 42, 'op-124'),
        )

    def test_unicode_and_separators_vector(self) -> None:
        fingerprint = self.service.fingerprint(
            'РосДорБанк',
            7,
            '  счёт № 1 , : "x"  ',
        )
        self.assertEqual(
            fingerprint.digest,
            '1bcba7e2cc6d80d49a224e3507c2835ede99ba49b48c83cdea7842a39908272c',
        )

    def test_empty_bank_rejected(self) -> None:
        for bank in ('', '   '):
            with self.assertRaises(ValueError):
                self.service.fingerprint(bank, 42, 'op-123')

    def test_error_message_without_input_values(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.service.fingerprint('   ', 42, 'op-123')
        self.assertNotIn('   ', str(caught.exception))

    def test_non_positive_account_rejected(self) -> None:
        for account_id in (0, -1, True):
            with self.assertRaises(ValueError):
                self.service.fingerprint('sberbank', account_id, 'op-123')

    def test_empty_source_ref_rejected(self) -> None:
        for source_ref in ('', '   '):
            with self.assertRaises(ValueError):
                self.service.fingerprint('sberbank', 42, source_ref)

    def test_missing_active_key_id(self) -> None:
        service = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='',
        )
        with self.assertRaises(StatementIdentityKeyUnavailable) as caught:
            service.fingerprint('sberbank', 42, 'op-123')
        self.assertNotIn('test-key-1', str(caught.exception))

    def test_active_key_not_in_keyring(self) -> None:
        service = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='retired-key',
        )
        with self.assertRaises(StatementIdentityKeyUnavailable) as caught:
            service.fingerprint('sberbank', 42, 'op-123')
        message = str(caught.exception)
        self.assertNotIn('retired-key', message)
        self.assertNotIn(KEY_ONE_HEX, message)


class StatementIdFingerprintConfigTest(SimpleTestCase):
    def test_keys_loaded_from_settings(self) -> None:
        with override_settings(
            STATEMENT_ID_HMAC_KEYS=json.dumps({'test-key-1': KEY_ONE_HEX}),
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
        ):
            service = StatementIdFingerprintService()
            fingerprint = service.fingerprint('sberbank', 42, 'op-123')
        self.assertEqual(
            fingerprint.digest,
            '7b9f67b50155d71fc7d3d9b5ca4872c8e24eed548af1b38b574f05a33a211fbe',
        )
        self.assertEqual(fingerprint.key_id, 'test-key-1')

    def test_unconfigured_does_not_break_startup(self) -> None:
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
        ):
            service = StatementIdFingerprintService()
            self.assertEqual(service.available_key_ids(), frozenset())
            with self.assertRaises(StatementIdentityKeyUnavailable):
                service.fingerprint('sberbank', 42, 'op-123')

    def test_no_secret_key_fallback(self) -> None:
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
            SECRET_KEY='fallback-candidate',
        ):
            service = StatementIdFingerprintService()
            with self.assertRaises(StatementIdentityKeyUnavailable):
                service.fingerprint('sberbank', 42, 'op-123')

    def test_secret_key_independence(self) -> None:
        keys = {'test-key-1': KEY_ONE}
        first = StatementIdFingerprintService(
            keys=keys,
            active_key_id='test-key-1',
        )
        with override_settings(SECRET_KEY='completely-different-secret'):
            second = StatementIdFingerprintService(
                keys=keys,
                active_key_id='test-key-1',
            )
            self.assertEqual(
                first.fingerprint('sberbank', 42, 'op-123'),
                second.fingerprint('sberbank', 42, 'op-123'),
            )

    def test_invalid_config_raises_without_values(self) -> None:
        invalid_configs = (
            '{not json',
            '["not", "a", "dict"]',
            json.dumps({'test-key-1': 'not-hex'}),
            json.dumps({'test-key-1': 'aabbcc'}),
            json.dumps({'': KEY_ONE_HEX}),
        )
        for raw in invalid_configs:
            with (
                override_settings(
                    STATEMENT_ID_HMAC_KEYS=raw,
                    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
                ),
                self.assertRaises(ImproperlyConfigured) as caught,
            ):
                StatementIdFingerprintService()
            message = str(caught.exception)
            self.assertNotIn(raw, message)
            self.assertNotIn(KEY_ONE_HEX, message)
            self.assertNotIn('aabbcc', message)
            self.assertNotIn('not-hex', message)

    def test_short_explicit_key_rejected(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            StatementIdFingerprintService(
                keys={'test-key-1': b'too-short'},
                active_key_id='test-key-1',
            )


class StatementIdFingerprintRotationTest(SimpleTestCase):
    def test_lookup_returns_fingerprint_per_key(self) -> None:
        service = StatementIdFingerprintService(
            keys={'test-key-2': KEY_TWO, 'test-key-1': KEY_ONE},
            active_key_id='test-key-2',
        )
        fingerprints = service.lookup_fingerprints('sberbank', 42, 'op-123')
        self.assertEqual(
            fingerprints,
            (
                StatementFingerprint(
                    digest=(
                        '7b9f67b50155d71fc7d3d9b5ca4872c8e24eed548af1b38b'
                        '574f05a33a211fbe'
                    ),
                    key_id='test-key-1',
                ),
                StatementFingerprint(
                    digest=(
                        '8b0549192ef4737679c61b5713d361af4d710416b6c0a2ea'
                        '6e1d780aee256fa1'
                    ),
                    key_id='test-key-2',
                ),
            ),
        )

    def test_old_key_lookup_after_rotation(self) -> None:
        before = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )
        old_fingerprint = before.fingerprint('sberbank', 42, 'op-123')
        rotated = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE, 'test-key-2': KEY_TWO},
            active_key_id='test-key-2',
        )
        new_fingerprint = rotated.fingerprint('sberbank', 42, 'op-123')
        self.assertEqual(new_fingerprint.key_id, 'test-key-2')
        self.assertNotEqual(old_fingerprint.digest, new_fingerprint.digest)
        self.assertIn(
            old_fingerprint,
            rotated.lookup_fingerprints('sberbank', 42, 'op-123'),
        )
        self.assertEqual(
            rotated.available_key_ids(),
            frozenset({'test-key-1', 'test-key-2'}),
        )

    def test_lookup_validates_inputs(self) -> None:
        service = StatementIdFingerprintService(
            keys={'test-key-1': KEY_ONE},
            active_key_id='test-key-1',
        )
        with self.assertRaises(ValueError):
            service.lookup_fingerprints('sberbank', 42, '  ')

    def test_lookup_without_keys_returns_empty(self) -> None:
        service = StatementIdFingerprintService(keys={}, active_key_id='')
        self.assertEqual(
            service.lookup_fingerprints('sberbank', 42, 'op-123'),
            (),
        )
