"""Explicit registry of application-owned Main Sequence MetaTables."""

from .base import Base
from .documents import DocumentRecord, DocumentReviewRecord, DocumentRevisionRecord
from .evidence import FieldEvidenceRecord, RawDocumentChunkRecord, RawDocumentRecord
from .operations import (
    AuditEventRecord,
    ProcessingRunRecord,
    ReconciliationEvaluationRecord,
    ReconciliationFindingRecord,
)
from .parsing import ParsingPolicyRecord, ParsingResultRecord
from .person import PersonRecord, PersonRevisionRecord
from .requirements import (
    AssignmentDocumentRecord,
    DocumentSchemaRecord,
    DocumentSetVersionRecord,
    PersonDocumentSetRecord,
)

__all__ = ["Base", "metatable_models"]


def metatable_models() -> tuple[type[Base], ...]:
    """Stable, explicit provider boundary; no network calls or discovery on import."""
    return (
        PersonRecord,
        PersonRevisionRecord,
        DocumentSchemaRecord,
        DocumentSetVersionRecord,
        PersonDocumentSetRecord,
        DocumentRecord,
        DocumentRevisionRecord,
        AssignmentDocumentRecord,
        DocumentReviewRecord,
        RawDocumentRecord,
        RawDocumentChunkRecord,
        FieldEvidenceRecord,
        ReconciliationEvaluationRecord,
        ReconciliationFindingRecord,
        ProcessingRunRecord,
        AuditEventRecord,
        ParsingPolicyRecord,
        ParsingResultRecord,
    )
