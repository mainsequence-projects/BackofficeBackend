"""Explicit registry of application-owned Main Sequence MetaTables."""

from .base import Base
from .cases import CaseTypeDocumentSetRecord, CaseTypeRecord
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
    CaseRecord,
    DocumentSchemaRecord,
    DocumentSetVersionRecord,
)
from .reviewers import CaseReviewerRecord

__all__ = ["Base", "metatable_models"]


def metatable_models() -> tuple[type[Base], ...]:
    """Stable, explicit provider boundary; no network calls or discovery on import."""
    return (
        PersonRecord,
        PersonRevisionRecord,
        DocumentSchemaRecord,
        DocumentSetVersionRecord,
        CaseRecord,
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
        CaseReviewerRecord,
        CaseTypeRecord,
        CaseTypeDocumentSetRecord,
    )
