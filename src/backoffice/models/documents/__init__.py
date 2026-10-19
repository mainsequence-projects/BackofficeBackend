"""Canonical document facts shared by every document-set workflow."""

from .bank_statement import BankStatement
from .employer_confirmation import EmployerConfirmation
from .employment_contract import EmploymentContract
from .kyc_questionnaire import KYCQuestionnaire
from .loan_contract import LoanContract
from .national_identity_card import NationalIdentityCard
from .passport import Passport
from .payslip import Payslip
from .residence_permit import ResidencePermit
from .source_of_funds_evidence import SourceOfFundsEvidence
from .tax_clearance_certificate import TaxClearanceCertificate
from .tax_return import TaxReturn
from .utility_bill import UtilityBill

__all__ = [
    "NationalIdentityCard",
    "Passport",
    "ResidencePermit",
    "UtilityBill",
    "BankStatement",
    "EmploymentContract",
    "Payslip",
    "TaxReturn",
    "SourceOfFundsEvidence",
    "KYCQuestionnaire",
    "LoanContract",
    "EmployerConfirmation",
    "TaxClearanceCertificate",
]
