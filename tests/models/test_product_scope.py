"""Product V1 uses document facts; biometrics are explicitly future V2 scope."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.backoffice.models.comparison import ComparisonSelector
from src.backoffice.models.document import DocumentInstance
from src.backoffice.models.document_set import DocumentOption
from src.backoffice.schemas.catalog import document_schema
from src.backoffice.schemas.drafts import get_draft_model
from src.backoffice.schemas.registry import (
    DOCUMENT_MODELS,
    LATEST_DOCUMENT_VERSIONS,
    get_document_model,
)


@pytest.mark.parametrize("field", ["portrait_reference", "portrait_reference.raw_document_uid"])
def test_v1_policies_cannot_reintroduce_portraits_through_historical_schemas(field):
    with pytest.raises(ValidationError, match="product V2 scope"):
        DocumentOption(document_type="passport", schema_version=1, required_fields=[field])
    with pytest.raises(ValidationError, match="product V2 scope"):
        ComparisonSelector(document_type="passport", schema_version=1, field=field)


@pytest.mark.parametrize("kind,version", LATEST_DOCUMENT_VERSIONS.items())
def test_current_document_schemas_do_not_collect_portraits(kind, version):
    pair = document_schema(kind, version)
    for schema in (pair.canonical_schema, pair.draft_schema):
        assert "portrait_reference" not in json.dumps(schema)
        assert "EvidenceRegion" not in schema.get("$defs", {})


@pytest.mark.parametrize("kind", ["national_identity_card", "passport"])
def test_current_identity_completion_does_not_accept_portrait_metadata(kind, document_fixture):
    version = LATEST_DOCUMENT_VERSIONS[kind]
    model = get_document_model(kind, version)
    payload = document_fixture(kind)
    assert model.model_validate(payload).full_name
    for parser in (model, get_draft_model(kind, version)):
        with pytest.raises(ValidationError, match="portrait_reference"):
            parser.model_validate({**payload, "portrait_reference": {"page_number": 1}})


@pytest.mark.parametrize("kind,version", DOCUMENT_MODELS)
def test_document_envelope_keeps_each_exact_historical_contract(kind, version, document_fixture):
    payload = document_fixture(kind)
    model = get_document_model(kind, version)
    if "portrait_reference" in model.model_fields:
        payload["portrait_reference"] = {"raw_document_uid": str(uuid4()), "page_number": 1}
    now = datetime.now(UTC)
    doc = DocumentInstance(
        uid=uuid4(),
        person_uid=uuid4(),
        revision=1,
        created_at=now,
        revision_created_at=now,
        submitted_at=now,
        schema_version=version,
        data=payload,
        raw_document_refs=[{"raw_document_uid": uuid4()}],
    )
    assert type(doc.data) is model
    assert (
        DocumentInstance.model_validate_json(doc.model_dump_json(exclude_computed_fields=True))
        == doc
    )
