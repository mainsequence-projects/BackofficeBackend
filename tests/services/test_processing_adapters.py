"""Provider boundary tests: signed envelopes, immutable checks and secret redaction."""

import base64
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from pypdf import PdfWriter

from src.backoffice.processing import adapters
from src.backoffice.processing.contracts import (
    Candidate,
    ClassificationResponse,
    ClassifyRequest,
    ParserFile,
)


class Response:
    def __init__(self, body, status=200):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("private upstream response and token")

    def iter_content(self, size):
        yield self.body


def request():
    return ClassifyRequest(
        files=[
            ParserFile(filename="source.png", content_base64=base64.b64encode(b"source").decode())
        ],
        document_types=[Candidate(document_type="passport", description="Identity document")],
    )


def session(function=None):
    return {
        "accessKeyId": "synthetic-access",
        "secretAccessKey": "synthetic-private",
        "sessionToken": "synthetic-session",
        "expiration": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "region": "eu-central-1",
        "service": "lambda",
        "functionUrl": function or adapters.ParsingMotor().function,
    }


def output():
    return {
        "pages": [
            {
                "source_file": "source.png",
                "page": 1,
                "source_sha256": "1" * 64,
                "page_sha256": "2" * 64,
                "document_type": "passport",
                "confidence": 0.6,
                "reason": "fixture",
                "model": "model",
                "cache_hit": False,
            }
        ]
    }


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(
        adapters.Secret, "get", lambda **kwargs: SimpleNamespace(value=SecretStr("synthetic-key"))
    )
    monkeypatch.delenv("BACKOFFICE_PARSER_AUTH", raising=False)
    monkeypatch.delenv("BACKOFFICE_PARSER_REGION", raising=False)
    monkeypatch.delenv("BACKOFFICE_PARSER_FUNCTION_URL", raising=False)


def test_sigv4_signs_exact_body_and_secret_is_header_only(key, monkeypatch):
    seen = []

    def get(url, **kwargs):
        assert url.endswith("/session")
        assert kwargs["headers"] == {"x-api-key": "synthetic-key"}
        assert kwargs["allow_redirects"] is False
        return Response(session())

    def post(url, **kwargs):
        seen.append(url)
        assert url.endswith("/classify_json") and "synthetic" not in url
        headers = {k.lower(): v for k, v in kwargs["headers"].items()}
        assert headers["authorization"].startswith("AWS4-HMAC-SHA256")
        assert "/eu-central-1/lambda/aws4_request" in headers["authorization"]
        assert headers["x-amz-security-token"] == "synthetic-session"
        assert json.loads(kwargs["data"]) == request().model_dump(mode="json")
        return Response(output())

    monkeypatch.setattr(adapters.requests, "get", get)
    monkeypatch.setattr(adapters.requests, "post", post)
    result = adapters.ParsingMotor().classify(request())
    assert isinstance(result, ClassificationResponse) and len(seen) == 1
    assert "synthetic" not in result.model_dump_json()


def test_session_cannot_redirect_documents_or_credentials(key, monkeypatch):
    monkeypatch.setattr(
        adapters.requests, "get", lambda *a, **k: Response(session("https://attacker.invalid/"))
    )
    monkeypatch.setattr(
        adapters.requests,
        "post",
        lambda *a, **k: pytest.fail("Must not post to a changed session target"),
    )
    with pytest.raises(adapters.ProcessingError, match="session_target_mismatch"):
        adapters.ParsingMotor().classify(request())


@pytest.mark.parametrize(
    "response",
    [
        Response({"private": "synthetic-key"}, 500),
        Response({"pages": [{"confidence": "0.6"}]}),
        Response(b"x" * (2 * 1024 * 1024 + 1)),
    ],
)
def test_bad_provider_outputs_are_bounded_and_sanitized(key, monkeypatch, response, caplog):
    monkeypatch.setenv("BACKOFFICE_PARSER_AUTH", "api_key")
    monkeypatch.setattr(adapters.requests, "post", lambda *a, **k: response)
    with pytest.raises(adapters.ProcessingError) as error:
        adapters.ParsingMotor().classify(request())
    assert "synthetic" not in str(error.value) + caplog.text
    assert "private" not in str(error.value)


def test_bucket_reads_refresh_capability_and_verify_hash(monkeypatch):
    uid = str(uuid4())
    content = b"original"
    artifact = SimpleNamespace(
        uid=uid,
        bucket_name="backoffice-documents",
        content="https://bucket.invalid/signed?capability=private",
    )
    monkeypatch.setattr(adapters.Artifact, "get", lambda **kwargs: artifact)
    calls = []

    def get(url, **kwargs):
        assert "headers" not in kwargs
        assert kwargs["allow_redirects"] is False
        calls.append(url)
        return Response(content)

    monkeypatch.setattr(adapters.requests, "get", get)
    source = {"byte_count": len(content), "content_sha256": hashlib.sha256(content).hexdigest()}
    reference = {"artifact_uid": uid, "bucket_name": artifact.bucket_name}
    bucket = adapters.MainSequenceBucket()
    assert bucket.read(reference, source) == content
    source["content_sha256"] = "0" * 64
    with pytest.raises(adapters.ProcessingError, match="checksum_mismatch"):
        bucket.read(reference, source)
    assert len(calls) == 2


def test_pdf_page_limit_and_encryption_are_checked_before_upload():
    writer = PdfWriter()
    for _ in range(21):
        writer.add_blank_page(width=100, height=100)
    content = io.BytesIO()
    writer.write(content)
    with pytest.raises(adapters.ProcessingError, match="page_limit"):
        adapters.inspect_source(content.getvalue(), "application/pdf")
    writer.encrypt("password")
    content = io.BytesIO()
    writer.write(content)
    with pytest.raises(adapters.ProcessingError, match="encrypted"):
        adapters.inspect_source(content.getvalue(), "application/pdf")


def test_bucket_retries_reuse_verified_content_without_overwriting(monkeypatch):
    uid, digest = str(uuid4()), hashlib.sha256(b"source").hexdigest()
    source = {"uid": uid, "content_sha256": digest, "byte_count": 6}
    artifact = SimpleNamespace(
        uid=str(uuid4()), name=f"backoffice-{uid}-{digest}", bucket_name="backoffice-documents"
    )
    monkeypatch.setattr(adapters.Artifact, "filter", lambda **kwargs: [artifact])
    monkeypatch.setattr(
        adapters.Artifact,
        "upload_file",
        lambda *a, **k: pytest.fail("Existing source must not be overwritten"),
    )
    monkeypatch.setattr(adapters.MainSequenceBucket, "read", lambda *a: b"source")
    monkeypatch.delenv("BACKOFFICE_PARSING_PROCESSOR_UIDS", raising=False)
    assert adapters.MainSequenceBucket().put(source, b"source")["artifact_uid"] == artifact.uid
