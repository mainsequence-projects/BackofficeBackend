"""Explicit document registry; adding a version never replaces a historical contract."""

from functools import reduce
from operator import or_
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from ..models.documents import (
    BankStatement,
    EmployerConfirmation,
    EmploymentContract,
    KYCQuestionnaire,
    LoanContract,
    NationalIdentityCard,
    Passport,
    Payslip,
    ResidencePermit,
    SourceOfFundsEvidence,
    TaxClearanceCertificate,
    TaxReturn,
    UtilityBill,
)
from ..models.documents.identity_facts import NationalIdentityCardV3, PassportV2
from ..models.documents.v2 import DOCUMENT_MODELS_V2

DocumentType = Literal[
    "national_identity_card",
    "passport",
    "residence_permit",
    "utility_bill",
    "bank_statement",
    "employment_contract",
    "payslip",
    "tax_return",
    "source_of_funds_evidence",
    "kyc_questionnaire",
    "loan_contract",
    "employer_confirmation",
    "tax_clearance_certificate",
]

DocumentPayload = Annotated[
    NationalIdentityCard
    | Passport
    | ResidencePermit
    | UtilityBill
    | BankStatement
    | EmploymentContract
    | Payslip
    | TaxReturn
    | SourceOfFundsEvidence
    | KYCQuestionnaire
    | LoanContract
    | EmployerConfirmation
    | TaxClearanceCertificate,
    Field(discriminator="document_type"),
]

DOCUMENT_MODELS = MappingProxyType(
    {
        (model.model_fields["document_type"].default, 1): model
        for model in (
            NationalIdentityCard,
            Passport,
            ResidencePermit,
            UtilityBill,
            BankStatement,
            EmploymentContract,
            Payslip,
            TaxReturn,
            SourceOfFundsEvidence,
            KYCQuestionnaire,
            LoanContract,
            EmployerConfirmation,
            TaxClearanceCertificate,
        )
    }
    | {(model.model_fields["document_type"].default, 2): model for model in DOCUMENT_MODELS_V2}
    | {("national_identity_card", 3): NationalIdentityCardV3, ("passport", 2): PassportV2}
)
DOCUMENT_ADAPTER = TypeAdapter(DocumentPayload)

PreviousDocumentPayload = Annotated[
    reduce(or_, DOCUMENT_MODELS_V2), Field(discriminator="document_type")
]

# The envelope accepts current fields, then validates its exact recorded version.
LATEST_DOCUMENT_VERSIONS = MappingProxyType(
    {
        kind: max(version for candidate, version in DOCUMENT_MODELS if candidate == kind)
        for kind, _ in DOCUMENT_MODELS
    }
)
LatestDocumentPayload = Annotated[
    reduce(
        or_,
        (DOCUMENT_MODELS[(kind, version)] for kind, version in LATEST_DOCUMENT_VERSIONS.items()),
    ),
    Field(discriminator="document_type"),
]


def get_document_model(document_type: str, schema_version: int = 1):
    """Resolve an exact contract; unknown versions never fall back to the latest."""
    try:
        return DOCUMENT_MODELS[(document_type, schema_version)]
    except KeyError as exc:
        raise ValueError(
            f"Unknown document schema: {document_type} version {schema_version}"
        ) from exc


def resolve_field_schema(model, path: str) -> dict:
    """Resolve an object field path, such as statement_period.end_date, for policy validation."""
    if path.split(".")[0] == "portrait_reference":
        raise ValueError("Portrait requirements and face comparison are product V2 scope")
    root = model.model_json_schema()
    current = root
    for component in path.split("."):
        if "anyOf" in current:
            choices = [item for item in current["anyOf"] if item.get("type") != "null"]
            if len(choices) != 1:
                raise ValueError(f"Ambiguous policy field: {path}")
            current = choices[0]
        if "$ref" in current:
            current = root["$defs"][current["$ref"].rsplit("/", 1)[1]]
        try:
            current = current["properties"][component]
        except KeyError as exc:
            raise ValueError(f"Unknown policy field: {path}") from exc
    return current
