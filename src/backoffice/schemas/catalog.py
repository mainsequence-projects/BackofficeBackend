"""Portable form contracts shared by future REST and MCP adapters."""

import hashlib
import json
from typing import Any

from pydantic import Field

from ..models.common import ContractModel
from .drafts import get_draft_model
from .registry import DocumentType, get_document_model


class DocumentSchema(ContractModel):
    document_type: DocumentType = Field(
        title="Document type",
        description="Stable discriminator identifying this document contract.",
    )
    version: int = Field(
        ge=1,
        title="Schema version",
        description="Exact supported contract version, with no fallback to another version.",
    )
    canonical_schema: dict[str, Any] = Field(
        title="Canonical schema",
        description="Validation JSON Schema for complete document attributes, including field titles, descriptions and required fields.",
    )
    draft_schema: dict[str, Any] = Field(
        title="Draft schema",
        description="Validation JSON Schema derived from the canonical model for incomplete editing or extraction.",
    )
    content_sha256: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        title="Content checksum",
        description="SHA-256 of the canonical JSON encoding of the canonical_schema and draft_schema pair.",
    )


def document_schema(document_type: str, version: int = 1) -> DocumentSchema:
    model = get_document_model(document_type, version)
    schemas = {
        "canonical_schema": model.model_json_schema(mode="validation"),
        "draft_schema": get_draft_model(document_type, version).model_json_schema(
            mode="validation"
        ),
    }
    encoded = json.dumps(schemas, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return DocumentSchema(
        document_type=document_type,
        version=version,
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        **schemas,
    )
