"""Fixtures and tests for persisted v2 observations through the shared document engine."""


def fixture_evidence(payload, filename):
    def leaves(value, pointer=""):
        if isinstance(value, dict) and value:
            for key, item in value.items():
                yield from leaves(item, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list) and value:
            for index, item in enumerate(value):
                yield from leaves(item, f"{pointer}/{index}")
        elif pointer != "/document_type":
            yield pointer, value

    return {
        "contract_version": 2,
        "normalization_version": "fixture-v1",
        "evidence_complete": True,
        "field_evidence": [
            {
                "pointer": p,
                "candidates": [
                    {
                        "reader_id": "vision",
                        "model": "fixture",
                        "value": v,
                        "locations": [{"source_file": filename, "page": 1}]
                        if v is not None
                        else [],
                    }
                ],
                "selected_reader_id": "vision" if v is not None else None,
                "agreement": "single_reader" if v is not None else "missing",
            }
            for p, v in leaves(payload)
        ],
    }
