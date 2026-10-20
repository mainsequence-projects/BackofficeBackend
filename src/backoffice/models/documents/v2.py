"""Source-tolerant contracts; published version 1 models remain unchanged.

Keep the identifying facts and the document's primary evidence required. Optional
details must stay unknown when absent, rather than being invented for completion.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ..common import CurrencyCode, Money, NonEmptyStr
from .bank_statement import BankStatement
from .employer_confirmation import EmployerConfirmation
from .kyc_questionnaire import KYCQuestionnaire
from .loan_contract import LoanContract
from .national_identity_card import NationalIdentityCard
from .payslip import Payslip
from .residence_permit import ResidencePermit
from .tax_clearance_certificate import TaxClearanceCertificate
from .utility_bill import UtilityBill


class NationalIdentityCardV2(NationalIdentityCard):
    """Identity happy-case facts without mandatory extraction metadata."""

    issuing_country: NonEmptyStr | None = Field(
        default=None,
        title="Issuing country",
        description="Country or issuing authority when explicitly extracted from the source; absent from the happy-case field contract and never guessed from a person's address.",
    )
    validity_type: Literal["fixed_term", "permanent", "unknown"] | None = Field(
        default=None,
        title="Validity type",
        description="Explicit validity classification when available; null means not classified, never permanent. A printed expiry can establish validity without this metadata.",
    )


class BankStatementV2(BankStatement):
    """Account-holder, account and period facts supplied by statement happy cases."""

    bank_name: NonEmptyStr | None = Field(
        default=None,
        title="Bank name",
        description="Institution issuing the statement when extracted; optional in the happy-case field contract.",
    )
    currency: CurrencyCode | None = Field(
        default=None,
        title="Currency",
        description="ISO three-letter account-level currency when established; individual monetary amounts still require their own currency, never an inferred account currency.",
    )

    @model_validator(mode="after")
    def balance_currencies(self) -> Self:
        if self.currency is not None:
            for balance in (self.opening_balance, self.closing_balance):
                if balance is not None and balance.currency != self.currency:
                    raise ValueError("balance currency must match statement currency")
        return self


class TaxClearanceCertificateV2(TaxClearanceCertificate):
    """Authority's stated arrears result without a mandatory duplicate transcription."""

    statement_as_printed: NonEmptyStr | None = Field(
        default=None,
        title="Statement as printed",
        description="Verbatim wording when transcribed; optional alongside the happy case's normalized arrears statement. Supporting original source and review remain separate requirements.",
    )


class ResidencePermitV2(ResidencePermit):
    """Residence permit with an optional printed category."""

    permit_type: NonEmptyStr | None = Field(
        default=None,
        title="Permit type",
        description="Printed permit category or class, if stated; absence does not establish entitlements.",
    )


class UtilityBillV2(UtilityBill):
    """Address evidence without requiring an explicitly printed service category."""

    utility_type: NonEmptyStr | None = Field(
        default=None,
        title="Utility type",
        description="Service category explicitly stated by the bill, if present; do not infer it solely from the provider name.",
    )


class PayslipV2(Payslip):
    """Pay evidence requiring net pay, with gross pay only when supplied."""

    gross_pay: Money | None = Field(
        default=None,
        title="Gross pay",
        description="Total pay before deductions, if stated; do not reconstruct it from net pay or assume missing deductions are zero.",
    )

    @model_validator(mode="after")
    def pay_currencies(self) -> Self:
        if self.gross_pay is not None and self.gross_pay.currency != self.net_pay.currency:
            raise ValueError("gross_pay and net_pay must use the same currency")
        if self.deductions is not None and self.deductions.currency != self.net_pay.currency:
            raise ValueError("deductions must use the pay currency")
        return self


class LoanContractV2(LoanContract):
    """Loan terms that need not carry a separate contract reference."""

    contract_number: NonEmptyStr | None = Field(
        default=None,
        title="Contract number",
        description="Contract reference exactly as printed, if present, preserving leading zeros; never generated from the upload or document UID.",
    )


class EmployerConfirmationV2(EmployerConfirmation):
    """Employer income evidence without requiring an unstated averaging basis."""

    income_basis: Literal["single_month", "monthly_average", "not_stated"] | None = Field(
        default=None,
        title="Income basis",
        description="Whether the source describes one month or an average; null or not_stated means the basis is unknown, not a single-month assumption.",
    )


class KYCQuestionnaireV2(KYCQuestionnaire):
    """Questionnaire facts with optional external-form metadata and outgoing estimate."""

    expected_monthly_outflow: Money | None = Field(
        default=None,
        title="Expected monthly outflow",
        description="Expected outgoing funds per calendar month, if requested and answered; absent is unknown, not zero.",
    )
    completed_at: AwareDatetime | None = Field(
        default=None,
        title="Completed at",
        description="Timezone-aware completion instant when recorded by the source or application; never substitute the upload time for an undated external form.",
    )
    questionnaire_version: NonEmptyStr | None = Field(
        default=None,
        title="Questionnaire version",
        description="Version of the questionnaire when established by the source or application; null for an external form without a version.",
    )

    @model_validator(mode="after")
    def nonnegative_expected_flows(self) -> Self:
        for flow in (self.expected_monthly_inflow, self.expected_monthly_outflow):
            if flow is not None and flow.amount < 0:
                raise ValueError("expected monthly flows must not be negative")
        return self


DOCUMENT_MODELS_V2 = (
    NationalIdentityCardV2,
    BankStatementV2,
    TaxClearanceCertificateV2,
    ResidencePermitV2,
    UtilityBillV2,
    PayslipV2,
    LoanContractV2,
    EmployerConfirmationV2,
    KYCQuestionnaireV2,
)
