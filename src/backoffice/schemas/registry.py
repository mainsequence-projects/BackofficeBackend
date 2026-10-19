"""Explicit document registry; adding a version never replaces a historical contract."""

from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from ..models.documents import (
    BankStatement,
    EmploymentContract,
    KYCQuestionnaire,
    NationalIdentityCard,
    Passport,
    Payslip,
    ResidencePermit,
    SourceOfFundsEvidence,
    TaxReturn,
    UtilityBill,
)

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
    | KYCQuestionnaire,
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
        )
    }
)
DOCUMENT_ADAPTER = TypeAdapter(DocumentPayload)


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
