"""Coordinate bank statement identity between parsers and stored fingerprints.

The parser owns the bank provenance and knows whether a reference is a real
technical bank identifier. This service turns that into the metadata stored
next to a row or movement, and decides whether a row may be posted
automatically or must go to the existing manual reconciliation path.

Every decision here is fail-closed: a missing key, an unreadable stored
version, an unverified historical fingerprint, or a match against one is a
reason for manual review, never for automatic posting. Manual review does
not erase a proven technical identity: a genuine parser ID with a valid
active-key fingerprint stays trusted so later representations can be linked.
"""

from dataclasses import dataclass
from typing import Final

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

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

MANUAL_REASON_KEY_UNAVAILABLE: Final[Promise] = _(
    'Идентификатор операции не проверен: нужен ключ отпечатков. '
    'Требуется ручная сверка.',
)
MANUAL_REASON_STORED_KEY_UNAVAILABLE: Final[Promise] = _(
    'Идентификатор операции не проверен: отпечаток создан недоступным '
    'ключом. Требуется ручная сверка.',
)
MANUAL_REASON_UNVERIFIED_HISTORY: Final[Promise] = _(
    'Идентификатор операции не проверен: в счёте есть исторические '
    'неподтверждённые отпечатки. Требуется ручная сверка.',
)
MANUAL_REASON_MATCHED_UNVERIFIED: Final[Promise] = _(
    'Найдено неподтверждённое совпадение с уже учтённой операцией. '
    'Требуется ручная сверка.',
)
MANUAL_REASON_UNKNOWN_BANK: Final[Promise] = _(
    'Банк выписки не определён, идентификатор нельзя проверить. '
    'Требуется ручная сверка.',
)
MANUAL_REASON_DUPLICATE_PRESENTATION: Final[Promise] = _(
    'Найдено доказанное повторное представление операции. '
    'Решение принимается по исходной строке.',
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
    duplicate_of_id: int | None = None
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
            self._repository.save_upload_bank_code(upload, parsed_bank_code)
            saved = parsed_bank_code
        return saved or None

    def classify_incoming(
        self,
        *,
        account_id: int,
        bank_code: str | None,
        source_ref: str | None,
        trusted_reference: bool,
        exclude_upload_id: int | None = None,
    ) -> IncomingStatementIdentity:
        """Classify one parsed row against the account's stored identity.

        ``trusted_reference`` is true only for genuine technical bank IDs of
        a supported parser. Synthetic references (for example RosDorBank's
        number-and-date) may still be fingerprinted for same-file proof but
        never count as exact cross-file identity.
        """
        available = self._fingerprint_service.available_key_ids()
        identity = IncomingStatementIdentity()
        digests: set[str] = set()
        if source_ref:
            if not bank_code:
                return IncomingStatementIdentity(
                    version=0,
                    manual_reason=str(MANUAL_REASON_UNKNOWN_BANK),
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
                version=(active_hash.version if active_hash is not None else 0),
                trusted=trusted_reference and active_hash is not None,
            )
            digests = self._lookup_digests(
                account_id=account_id,
                bank_code=bank_code,
                source_ref=source_ref,
                available_key_ids=available,
            )

        matches = tuple(
            self._repository.untrusted_transactions(account_id, digests),
        )
        reason = self._required_guard_reason(
            account_id=account_id,
            available_key_ids=available,
            active_key_available=(
                identity.source_ref_hash is not None or not source_ref
            ),
            matches=matches,
        )
        if not source_ref:
            if reason:
                return self._manual(identity, reason, matches)
            return identity
        root_id = None
        if trusted_reference:
            root_id = self._repository.trusted_presentation_root_id(
                account_id,
                digests,
                available,
                exclude_upload_id=exclude_upload_id,
            )
        return self._classify_evidence(
            identity=identity,
            reason=reason,
            root_id=root_id,
            matches=matches,
            account_id=account_id,
            digests=digests,
            available_key_ids=available,
            trusted_reference=trusted_reference,
        )

    def _classify_evidence(
        self,
        *,
        identity: IncomingStatementIdentity,
        reason: str,
        root_id: int | None,
        matches: tuple[Transaction, ...],
        account_id: int,
        digests: set[str],
        available_key_ids: frozenset[str],
        trusted_reference: bool,
    ) -> IncomingStatementIdentity:
        """Apply guard and exact evidence without losing a proven root."""
        if reason:
            evidence_is_supported = reason not in {
                str(MANUAL_REASON_KEY_UNAVAILABLE),
                str(MANUAL_REASON_STORED_KEY_UNAVAILABLE),
            }
            if (
                evidence_is_supported
                and self._repository.trusted_movement_exists(
                    account_id,
                    digests,
                    available_key_ids,
                )
            ):
                return IncomingStatementIdentity(
                    source_ref_hash=identity.source_ref_hash,
                    key_id=identity.key_id,
                    version=identity.version,
                    trusted=True,
                    exact_duplicate=True,
                )
            return self._manual(
                identity,
                reason,
                matches,
                duplicate_of_id=root_id,
            )
        if trusted_reference and self._repository.trusted_movement_exists(
            account_id,
            digests,
            available_key_ids,
        ):
            return IncomingStatementIdentity(
                source_ref_hash=identity.source_ref_hash,
                key_id=identity.key_id,
                version=identity.version,
                trusted=True,
                exact_duplicate=True,
            )
        if trusted_reference and root_id is not None:
            return self._manual(
                identity,
                MANUAL_REASON_DUPLICATE_PRESENTATION,
                (),
                duplicate_of_id=root_id,
            )
        return identity

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

    def _required_guard_reason(
        self,
        *,
        account_id: int,
        available_key_ids: frozenset[str],
        active_key_available: bool,
        matches: tuple[Transaction, ...],
    ) -> str:
        """Return why automatic posting is unsafe before evidence is used."""
        if not active_key_available:
            return str(MANUAL_REASON_KEY_UNAVAILABLE)
        if self._repository.has_unavailable_identity(
            account_id,
            available_key_ids,
        ):
            return str(MANUAL_REASON_STORED_KEY_UNAVAILABLE)
        if matches:
            return str(MANUAL_REASON_MATCHED_UNVERIFIED)
        if self._repository.has_untrusted_identity(account_id):
            return str(MANUAL_REASON_UNVERIFIED_HISTORY)
        return ''

    @staticmethod
    def _manual(
        identity: IncomingStatementIdentity,
        reason: str | Promise,
        matches: tuple[Transaction, ...],
        *,
        duplicate_of_id: int | None = None,
    ) -> IncomingStatementIdentity:
        return IncomingStatementIdentity(
            source_ref_hash=identity.source_ref_hash,
            key_id=identity.key_id,
            version=identity.version,
            trusted=identity.trusted,
            manual_reason=str(reason),
            duplicate_of_id=duplicate_of_id,
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
