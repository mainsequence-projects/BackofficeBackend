"""Ensure generated form schemas and table documentation match the source."""

from scripts.export_contracts import ROOT, generated_files


def test_generated_contracts_are_current():
    for relative, expected in generated_files().items():
        assert (ROOT / relative).read_text() == expected, str(relative)
