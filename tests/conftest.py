"""Offline contract tests: no platform credentials or hosted writes are needed."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import requests

os.environ.setdefault("TDAG_ROOT_PATH", str(Path(tempfile.gettempdir()) / "backoffice-test-sdk"))


@pytest.fixture(autouse=True)
def prohibit_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Contract tests must not make HTTP requests")

    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture
def document_fixture():
    def load(kind):
        return json.loads(
            (Path(__file__).parent / "fixtures" / "documents" / f"{kind}.json").read_text()
        )

    return load
