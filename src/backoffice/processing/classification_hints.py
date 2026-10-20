"""What each document looks like, for the parser's classifier only (never a schema or policy).

Canonical schema descriptions say what we store ("Structured facts from a payslip"), not what
the page looks like, and they are English while the documents are Czech. On real packages the
classifier then sent the loan contract, employer letter and tax certificate to
source_of_funds_evidence. These hints carry the local titles; the schemas stay untouched, so
no schema hash or published version changes.
"""

HINTS = {
    "loan_contract": "Loan contract / credit agreement between a bank and a borrower (Czech: smlouva o úvěru, úvěrová smlouva): contract number, borrower name and birth number, loan amount, declared monthly net income, list of documents the borrower must supply.",
    "national_identity_card": "National identity card (Czech: občanský průkaz): photo, holder name, date of birth, card number, issue and expiry dates.",
    "passport": "Passport (Czech: cestovní pas): photo page with holder name, nationality, passport number, machine-readable zone.",
    "residence_permit": "Residence permit card for a foreign national (Czech: povolení k pobytu): holder, permit number, permit type, validity.",
    "utility_bill": "Utility or service bill used as proof of address (Czech: vyúčtování, faktura za elektřinu, plyn nebo vodu, doklad o bydlišti): customer, supply address, provider, issue date, amount due.",
    "bank_statement": "Bank account statement (Czech: výpis z účtu): account holder, IBAN or account number, statement period, opening and closing balance, list of transactions.",
    "employment_contract": "Employment contract signed by employer and employee (Czech: pracovní smlouva): position, start date, salary terms, contract duration.",
    "payslip": "Monthly payslip (Czech: výplatní páska, výplatní lístek): employee, employer, pay period, gross pay, deductions, net pay.",
    "tax_return": "Personal income tax return filed by the taxpayer (Czech: daňové přiznání): tax period, declared and taxable income.",
    "source_of_funds_evidence": "Evidence of where specific money came from (sale contract, inheritance, gift deed) for a source-of-funds declaration. Not a loan contract, not an employer letter, not a tax certificate.",
    "kyc_questionnaire": "Know-your-customer questionnaire filled in by the client (Czech: dotazník KYC): occupation, purpose of the account, expected monthly inflows and outflows.",
    "employer_confirmation": "Letter from an employer confirming employment and income (Czech: potvrzení o zaměstnání a výši příjmu): employee, employer and company ID (IČO), position, employed since, average monthly net income, issue date, signature.",
    "tax_clearance_certificate": "Certificate issued by the tax authority about tax arrears (Czech: potvrzení o bezdlužnosti, Finanční úřad, č. j.): taxpayer, reference number, issue date, statement whether the taxpayer has arrears.",
}


def local_titles(kind: str) -> str:
    """Appended to the classifier description built from the schema."""
    return f" Recognise it by: {HINTS[kind]}" if kind in HINTS else ""
