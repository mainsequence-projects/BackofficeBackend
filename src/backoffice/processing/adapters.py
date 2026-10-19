"""Server-configured bucket, parser and Job adapters; no credentials in persisted state."""

import hashlib
import io
import os
import tempfile
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from mainsequence.client import Artifact, Job, Secret
from PIL import Image
from pypdf import PdfReader

from .contracts import (
    MAX_BYTES,
    MAX_PAGES,
    ClassificationResponse,
    ExtractionResponse,
    ParserSession,
)


class ProcessingError(Exception):
    """Only this bounded, application-owned code may cross a provider boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def inspect_source(content, media_type):
    if not content or len(content) > MAX_BYTES:
        raise ProcessingError("source_size_exceeded")
    try:
        if media_type == "application/pdf" and content.startswith(b"%PDF-"):
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ProcessingError("encrypted_pdf_not_supported")
            count = len(reader.pages)
        elif media_type in {"image/png", "image/jpeg"}:
            with Image.open(io.BytesIO(content)) as image:
                if image.format != {"image/png": "PNG", "image/jpeg": "JPEG"}[media_type]:
                    raise ProcessingError("source_media_type_mismatch")
                if image.width * image.height > 50_000_000 or getattr(image, "n_frames", 1) != 1:
                    raise ProcessingError("source_image_limits_exceeded")
                image.verify()
            count = 1
        else:
            raise ProcessingError("unsupported_processing_media_type")
    except ProcessingError:
        raise
    except Exception:
        raise ProcessingError("invalid_source_document") from None
    if not 1 <= count <= MAX_PAGES:
        raise ProcessingError("source_page_limit_exceeded")
    return count


def read_response(response, limit):
    """Bound compressed/chunked responses as decoded bytes, never trust Content-Length."""
    response.raise_for_status()
    chunks, total = [], 0
    for chunk in response.iter_content(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise ProcessingError("provider_response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def https_url(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise ProcessingError("invalid_provider_configuration")
    return url


class MainSequenceBucket:
    def __init__(self, name=None):
        self.name = name or os.environ.get("BACKOFFICE_DOCUMENT_BUCKET", "backoffice-documents")

    def put(self, source, content):
        """A source-specific content-addressed name is never intentionally overwritten."""
        name = f"backoffice-{source['uid']}-{source['content_sha256']}"
        try:
            # The SDK scopes this lookup/upload to the repository's Environment.
            matches = Artifact.filter(name=name, bucket_name=self.name)
            if len(matches) > 1:
                raise ProcessingError("bucket_object_ambiguous")
            if matches:
                artifact = matches[0]
            else:
                with tempfile.NamedTemporaryFile() as file:
                    file.write(content)
                    file.flush()
                    artifact = Artifact.upload_file(file.name, name=name, bucket_name=self.name)
            if artifact.name != name or artifact.bucket_name != self.name or not artifact.uid:
                raise ProcessingError("bucket_object_mismatch")
            reference = {"bucket_name": self.name, "artifact_uid": str(artifact.uid)}
            self.read(reference, source)
            # The API and Job have separate workload Users. Share only this source
            # with the explicitly configured processors, never with all bucket users.
            for uid in {
                x.strip()
                for x in os.environ.get("BACKOFFICE_PARSING_PROCESSOR_UIDS", "").split(",")
                if x.strip()
            }:
                artifact.attach_policy("viewer", principal_type="user", principal_uid=uid)
            return reference
        except ProcessingError:
            raise
        except Exception:
            raise ProcessingError("bucket_upload_unavailable") from None

    def read(self, reference, source):
        try:
            artifact = Artifact.get(uid=reference["artifact_uid"])
            if artifact.bucket_name != reference["bucket_name"]:
                raise ProcessingError("bucket_object_mismatch")
            # URL comes only from the authenticated platform, never from a caller/document.
            with requests.get(
                https_url(artifact.content), timeout=(10, 60), stream=True, allow_redirects=False
            ) as response:
                if response.status_code != 200:
                    raise ProcessingError("bucket_read_unavailable")
                content = read_response(response, MAX_BYTES)
            if (
                len(content) != source["byte_count"]
                or hashlib.sha256(content).hexdigest() != source["content_sha256"]
            ):
                raise ProcessingError("bucket_checksum_mismatch")
            return content
        except ProcessingError:
            raise
        except Exception:
            raise ProcessingError("bucket_read_unavailable") from None


class ParsingMotor:
    def __init__(self):
        self.base = (
            os.environ.get(
                "BACKOFFICE_PARSER_BASE_URL", "https://d31su4idgeitei.cloudfront.net/"
            ).rstrip("/")
            + "/"
        )
        self.function = (
            os.environ.get(
                "BACKOFFICE_PARSER_FUNCTION_URL",
                "https://mokpk7khaf3azp3fhb3h4ruiqm0gflxj.lambda-url.eu-central-1.on.aws/",
            ).rstrip("/")
            + "/"
        )
        self.region = os.environ.get("BACKOFFICE_PARSER_REGION", "eu-central-1")
        self.auth = os.environ.get("BACKOFFICE_PARSER_AUTH", "sigv4")
        https_url(self.base)
        https_url(self.function)
        if self.auth not in {"sigv4", "api_key"}:
            raise ProcessingError("invalid_provider_configuration")

    def call(self, path, request, response_model):
        try:
            secret = Secret.get(name="AWS_BEDROOCK_FINTECHERS_APIKEY")
            if not secret.value:
                raise ProcessingError("parser_secret_unavailable")
            token = secret.value.get_secret_value()
            body = request.model_dump_json().encode()
            headers = {"content-type": "application/json", "x-api-key": token}
            url = self.base + path
            if self.auth == "sigv4":
                with requests.get(
                    self.base + "session",
                    headers={"x-api-key": token},
                    timeout=(10, 30),
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    session = ParserSession.model_validate_json(read_response(response, 16_384))
                if (
                    session.functionUrl.rstrip("/") + "/" != self.function
                    or session.region != self.region
                ):
                    raise ProcessingError("parser_session_target_mismatch")
                if datetime.fromisoformat(
                    session.expiration.replace("Z", "+00:00")
                ) <= datetime.now(UTC):
                    raise ProcessingError("parser_session_expired")
                url = self.function + path
                credentials = Credentials(
                    session.accessKeyId.get_secret_value(),
                    session.secretAccessKey.get_secret_value(),
                    session.sessionToken.get_secret_value(),
                )
                signed = AWSRequest(method="POST", url=url, data=body, headers=headers)
                SigV4Auth(credentials, "lambda", self.region).add_auth(signed)
                headers = dict(signed.headers)
            with requests.post(
                url,
                data=body,
                headers=headers,
                timeout=(10, 180),
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.status_code == 404:
                    raise ProcessingError("parser_endpoint_unavailable")
                return response_model.model_validate_json(read_response(response, 2 * 1024 * 1024))
        except ProcessingError:
            raise
        except Exception:
            # Provider errors/validation can contain API keys, STS material or document bytes.
            raise ProcessingError("parser_request_failed") from None

    def classify(self, request):
        from .evidence_contracts import ClassificationResponseV2

        response = (
            ClassificationResponseV2
            if getattr(request, "contract_version", 1) == 2
            else ClassificationResponse
        )
        return self.call("classify_json", request, response)

    def extract(self, request):
        from .evidence_contracts import ExtractionResponseV2

        response = (
            ExtractionResponseV2
            if getattr(request, "contract_version", 1) == 2
            else ExtractionResponse
        )
        return self.call("extract_typed_json", request, response)

    def compare(self, request):
        from .comparison_contracts import CompareDocumentsResponse

        response = self.call("compare_documents_json", request, CompareDocumentsResponse)
        return response.validate_request(request)


class MainSequenceDispatcher:
    def dispatch(self, uid):
        try:
            configured = os.environ.get("BACKOFFICE_EXTRACTION_JOB_UID")
            job = (
                Job.get(uid=configured)
                if configured
                else Job.get(name="Back Office document extraction")
            )
            answer = job.run_job(command_args=["--run-uid", str(uid)], timeout=30)
            return answer.get("uid") or answer.get("job_run_uid")
        except Exception:
            raise ProcessingError("processing_dispatch_unavailable") from None
