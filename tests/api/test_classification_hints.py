"""The classifier gets local-language descriptions and two readers are the default."""

from src.backoffice.processing import workflow
from src.backoffice.processing.classification_hints import HINTS, classifier_description
from src.backoffice.schemas.registry import DOCUMENT_MODELS


def test_every_hint_names_a_published_document_type_and_falls_back_to_the_schema():
    kinds = {kind for kind, _ in DOCUMENT_MODELS}
    assert set(HINTS) <= kinds
    assert "potvrzení o zaměstnání" in classifier_description("employer_confirmation", {})
    assert classifier_description("unknown_kind", {"description": "Schema text"}) == "Schema text"


def test_two_independent_readers_are_the_default(monkeypatch):
    monkeypatch.delenv("BACKOFFICE_EXTRACTION_READER_MODE", raising=False)
    assert workflow.configured_reader_mode() == "independent_readers"
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "single")
    assert workflow.configured_reader_mode() == "single"
