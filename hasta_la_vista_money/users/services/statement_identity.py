"""Coordinate bank statement identity between parsers and stored fingerprints.

The parser owns the bank provenance and knows whether a reference is a real
technical bank identifier. This service turns that into the metadata stored
next to a row or movement, and decides whether a row may be posted
automatically or must go to the existing manual reconciliation path.

Every decision here is fail-closed: a missing key, an unreadable stored
version, an unverified historical fingerprint, or a match against one is a
reason for manual review, never for automatic posting.
"""

from dataclasses import dataclass

from django.utils.translation import gettext as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.repositories.statement_identity_repository import (  # noqa: E501
    StatementIdentityRepository,
)
from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementFingerprint,
    StatementIdentityKeyUnavailable,
    StatementIdFingerprintService,
)

MANUAL_REASON_KEY_UNAVAILABLE = _(
    'Идентификатор операции не проверен: нужен ключ отпечатков. '
    'Требуется ручная сверка.',
)
MANUAL_REASON_STORED_KEY_UNAVAILABLE = _(
    'Идентификатор операции не проверен: отпечаток создан недоступным '
    'ключом. Требуется ручная сверка.',
)
MANUAL_REASON_UNVERIFIED_HISTORY = _(
    'Идентификатор операции не проверен: в счёте есть исторические '
    'неподтверждённые отпечатки. Требуется ручная сверка.',
)
MANUAL_REASON_MATCHED_UNVERIFIED = _(
    'Найдено неподтверждённое совпадение с уже учтённой операцией. '
    'Требуется ручная сверка.',
)
MANUAL_REASON_UNKNOWN_BANK = _(
    'Банк выписки не определён, идентификатор нельзя проверить. '
    'Требуется ручная сверка.',
)


class StatementIdentityConflictError(ValueError):
    """The parser now names a different bank than the upload snapshot."""


@dataclass(frozen=True)
class IncomingStatementIdentity:
    """Identity metadata of one parsed statement row."""

    source_ref_hash: str | None = None
    key_id: str = ''
    version: int = constants.STATEMENT_ID_FINGERPRINT_VERSION
    trusted: bool = False
    manual_reason: str = ''
    exact_duplicate: bool = False
    matched_transactions: tuple[Transaction, ...] = ()

    @property
    def manual(self) -> bool:
        """Whether the row must be decided by the user, not posted."""
        return bool(self.manual_reason)


class StatementIdentityService:
    """Resolve parser provenance and stored fingerprint decisions."""

    #: Parsers of these banks yield genuine technical operation identifiers.
    TRUSTED_REFERENCE_BANK_CODES = frozenset(
        {
            constants.BANK_CODE_RAIFFEISEN,
            constants.BANK_CODE_SBERBANK,
            constants.BANK_CODE_OZON,
        },
    )

    def __init__(
        self,
        fingerprint_service: StatementIdFingerprintService,
        repository: StatementIdentityRepository,
    ) -> None:
        self._fingerprint_service = fingerprint_service
        self._repository = repository

    def reference_is_trusted(
        self,
        bank_code: str | None,
        source_ref: str | None,
    ) -> bool:
        """Trust only genuine technical identifiers of a known bank parser."""
        return bool(
            source_ref and bank_code in self.TRUSTED_REFERENCE_BANK_CODES,
        )

    def resolve_bank_code(
        self,
        upload: BankStatementUpload,
        parsed_bank_code: str | None,
    ) -> str | None:
        """Keep the upload's bank snapshot immutable, never guessing a bank.

        The caller holds the account lock. A differing parser result is an
        explicit conflict: the saved provenance is not overwritten.

        Raises:
            StatementIdentityConflictError: The parser now names another bank.
        """
        saved = upload.source_bank_code
        if saved and parsed_bank_code and saved != parsed_bank_code:
            raise StatementIdentityConflictError(parsed_bank_code)
        if not saved and parsed_bank_code:
            upload.source_bank_code = parsed_bank_code
            upload.save(update_fields=['source_bank_code'])
            saved = parsed_bank_code
        return saved or None

    def classify_incoming(
        self,
        *,
        account_id: int,
        bank_code: str | None,
        source_ref: str | None,
        trusted_reference: bool,
    ) -> IncomingStatementIdentity:
        """Classify one parsed row against the account's stored identity.

        ``trusted_reference`` is true only for genuine technical bank IDs of
        a supported parser. Synthetic references (for example RosDorBank's
        number-and-date) may still be fingerprinted for same-file proof but
        never count as exact cross-file identity.
        """
        if not source_ref:
            return IncomingStatementIdentity()
        available = self._fingerprint_service.available_key_ids()
        if not bank_code:
            return IncomingStatementIdentity(
                manual_reason=MANUAL_REASON_UNKNOWN_BANK,
            )

        active_hash = self._active_fingerprint(
            bank_code=bank_code,
            account_id=account_id,
            source_ref=source_ref,
        )
        identity = IncomingStatementIdentity(
            source_ref_hash=(
                active_hash.digest if active_hash is not None else None
            ),
            key_id=active_hash.key_id if active_hash is not None else '',
            version=(
                active_hash.version
                if active_hash is not None
                else constants.STATEMENT_ID_FINGERPRINT_VERSION
            ),
            trusted=trusted_reference and active_hash is not None,
        )
        digests = self._lookup_digests(
            account_id=account_id,
            bank_code=bank_code,
            source_ref=source_ref,
            available_key_ids=available,
        )
        if trusted_reference and (
            self._repository.trusted_exact_transaction_exists(
                account_id,
                digests,
            )
        ):
            return IncomingStatementIdentity(
                source_ref_hash=identity.source_ref_hash,
                key_id=identity.key_id,
                version=identity.version,
                trusted=True,
                exact_duplicate=True,
            )

        matches = tuple(
            self._repository.untrusted_transactions(account_id, digests),
        )
        reason = self._uncertainty_reason(
            account_id=account_id,
            available_key_ids=available,
            active_key_available=active_hash is not None,
            matches=matches,
        )
        if reason:
            return self._manual(identity, reason, matches)
        return identity

    def _uncertainty_reason(
        self,
        *,
        account_id: int,
        available_key_ids: frozenset[str],
        active_key_available: bool,
        matches: tuple[Transaction, ...],
    ) -> str:
        """Return why automatic posting is unsafe, or an empty string."""
        if not active_key_available:
            return MANUAL_REASON_KEY_UNAVAILABLE
        if self._repository.has_unavailable_identity(
            account_id,
            available_key_ids,
        ):
            return MANUAL_REASON_STORED_KEY_UNAVAILABLE
        if matches:
            return MANUAL_REASON_MATCHED_UNVERIFIED
        if self._repository.has_untrusted_identity(account_id):
            return MANUAL_REASON_UNVERIFIED_HISTORY
        return ''

    def same_file_posted(
        self,
        *,
        account_id: int,
        source_file_hash: str,
        source_row_position: int,
    ) -> bool:
        """Tell whether the same file position already produced a movement."""
        return self._repository.same_file_transaction_exists(
            account_id,
            source_file_hash,
            source_row_position,
        )

    @staticmethod
    def _manual(
        identity: IncomingStatementIdentity,
        reason: str,
        matches: tuple[Transaction, ...],
    ) -> IncomingStatementIdentity:
        return IncomingStatementIdentity(
            source_ref_hash=identity.source_ref_hash,
            key_id=identity.key_id,
            version=identity.version,
            trusted=False,
            manual_reason=reason,
            matched_transactions=matches,
        )

    def _active_fingerprint(
        self,
        *,
        bank_code: str,
        account_id: int,
        source_ref: str,
    ) -> StatementFingerprint | None:
        try:
            return self._fingerprint_service.fingerprint(
                bank_code,
                account_id,
                source_ref,
            )
        except StatementIdentityKeyUnavailable:
            return None

    def _lookup_digests(
        self,
        *,
        account_id: int,
        bank_code: str,
        source_ref: str,
        available_key_ids: frozenset[str],
    ) -> set[str]:
        if not available_key_ids:
            return set()
        digests: set[str] = set()
        for namespace in (bank_code, constants.STATEMENT_ID_LEGACY_BANK_CODE):
            digests.update(
                item.digest
                for item in self._fingerprint_service.lookup_fingerprints(
                    namespace,
                    account_id,
                    source_ref,
                )
            )
        return digests
