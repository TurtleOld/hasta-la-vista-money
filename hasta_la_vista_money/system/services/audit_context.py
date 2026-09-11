"""Context propagation for the current audit operation.

Audit entries created by the write-layer signals during one unit of work
share an ``operation_id`` and ``kind`` so the history can later show the
operation, not its individual object edits. Values travel through a
``ContextVar``, not the database transaction, so a context nested inside a
shared ``atomic`` block groups correctly.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID, uuid4

from hasta_la_vista_money.system.models import AuditOperationKind


@dataclass(frozen=True, slots=True)
class OperationContext:
    """One entry into ``audit_operation`` — an id paired with its kind."""

    operation_id: UUID
    kind: AuditOperationKind | None


_context: ContextVar[OperationContext | None] = ContextVar(
    'audit_operation_context',
    default=None,
)


@contextmanager
def audit_operation(
    kind: AuditOperationKind | None = None,
) -> Iterator[UUID]:
    """Tag every audit entry created within the block with one operation.

    A new ``operation_id`` and ``kind`` are minted on every entry, even a
    re-entrant one; a nested call overrides the outer one for the duration
    of its own block.
    """
    context = OperationContext(operation_id=uuid4(), kind=kind)
    token = _context.set(context)
    try:
        yield context.operation_id
    finally:
        _context.reset(token)


def current_operation_id() -> UUID | None:
    context = _context.get()
    return context.operation_id if context is not None else None


def current_operation_kind() -> AuditOperationKind | None:
    context = _context.get()
    return context.kind if context is not None else None
