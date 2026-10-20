"""The classifier gets local-language descriptions and two readers are the default."""

import pytest

from src.backoffice.processing import workflow
from src.backoffice.processing.classification_hints import HINTS, local_titles
from src.backoffice.schemas.registry import DOCUMENT_MODELS


def test_every_hint_names_a_published_document_type_and_falls_back_to_the_schema():
    kinds = {kind for kind, _ in DOCUMENT_MODELS}
    assert set(HINTS) <= kinds
    assert "potvrzení o zaměstnání" in local_titles("employer_confirmation")
    assert local_titles("unknown_kind") == ""


def test_two_independent_readers_are_the_default(monkeypatch):
    monkeypatch.delenv("BACKOFFICE_EXTRACTION_OCR_ENABLED", raising=False)
    monkeypatch.delenv("BACKOFFICE_EXTRACTION_READER_MODE", raising=False)
    assert workflow.configured_reader_mode() == "independent_readers"
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "single")
    assert workflow.configured_reader_mode() == "single"


@pytest.mark.parametrize(
    "enabled,legacy,expected",
    [
        ("false", None, "single"),
        ("true", None, "independent_readers"),
        ("FALSE", "single", "single"),
        ("false", "independent_readers", "invalid"),
        ("maybe", None, "invalid"),
    ],
)
def test_explicit_ocr_capability_flag(monkeypatch, enabled, legacy, expected):
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_OCR_ENABLED", enabled)
    monkeypatch.delenv("BACKOFFICE_EXTRACTION_READER_MODE", raising=False)
    if legacy:
        monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", legacy)
    assert workflow.configured_reader_mode() == expected
