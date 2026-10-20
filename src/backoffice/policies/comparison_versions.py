"""Opt-in illustrative policy versions using the same comparison evaluator."""

from ..models.comparison import ComparisonRule, ComparisonSelector
from ..models.document_set import DocumentSet


def with_comparisons(policy: DocumentSet) -> DocumentSet:
    definition = policy.model_dump()
    definition["version"] += 1
    if policy.key == "loan_requirements":
        rules = [
            ComparisonRule(
                key="monthly_net_income_consistency",
                description="Declared and employer-confirmed monthly net income must describe the same basis and match exactly; zero tolerance is illustrative and not credit approval.",
                topic="Monthly net income of the same employee, period and income basis",
                left=ComparisonSelector(
                    document_type="loan_contract",
                    field="declared_monthly_net_income.amount",
                    unit_field="declared_monthly_net_income.currency",
                    context_fields=["full_name"],
                ),
                right=ComparisonSelector(
                    document_type="employer_confirmation",
                    field="monthly_net_income.amount",
                    unit_field="monthly_net_income.currency",
                    context_fields=["employee_name", "income_basis"],
                ),
                operator="numeric",
            )
        ]
    else:
        rules = [
            ComparisonRule(
                key="identity_name_consistency",
                description="When both passport and national identity card are supplied, their holder names must refer to the same person; uncertainty requires review.",
                topic="Identity document holder's full name and birth date",
                left=ComparisonSelector(
                    document_type="passport", field="full_name", context_fields=["date_of_birth"]
                ),
                right=ComparisonSelector(
                    document_type="national_identity_card",
                    field="full_name",
                    context_fields=["date_of_birth"],
                ),
                operator="semantic",
                when_both_present=True,
            )
        ]
    definition["comparisons"] = [r.model_dump() for r in rules]
    definition["description"] = (
        "Illustrative evidence policy with cited cross-document comparisons. Completion means "
        "only that the versioned evidence checks passed, never account-opening or credit approval. "
        "Thresholds and coverage require business approval before production use."
    )
    return DocumentSet.model_validate(definition)


def _side(policy, document_type, field, unit=None, context=()):
    version = next(
        o.schema_version
        for r in policy.requirements
        for o in r.options
        if o.document_type == document_type
    )
    return ComparisonSelector(
        document_type=document_type,
        schema_version=version,
        field=field,
        unit_field=unit,
        context_fields=list(context),
    )


def with_loan_consistency(policy: DocumentSet) -> DocumentSet:
    """Next loan version: the same requirements plus cross-document consistency, using only
    the existing exact/numeric/semantic operators (decided by Back Office, never the parser)."""
    definition = policy.model_dump()
    definition["version"] += 1
    s = lambda *args, **kw: _side(policy, *args, **kw)  # noqa: E731
    # Real Bedrock answers "uncertain" unless the topic states the shared basis, which hid the
    # income mismatch; the bank defines these three as the same monthly net figure.
    income = (
        "Monthly net income in CZK of the same person for this loan application. The loan "
        "contract's declared monthly net income, the payslip's net pay for one calendar month and "
        "the employer-confirmed average monthly net income are all stated on the same monthly net basis."
    )
    for rule in definition["comparisons"]:
        if rule["key"] == "monthly_net_income_consistency":
            rule["topic"] = income
    rules = [
        ComparisonRule(
            key="income_contract_vs_payslip",
            description="Declared monthly net income must match the payslip's net pay; not credit approval.",
            topic=income,
            left=s("loan_contract", "declared_monthly_net_income.amount", "declared_monthly_net_income.currency", ["full_name"]),
            right=s("payslip", "net_pay.amount", "net_pay.currency", ["employee_name"]),
            operator="numeric",
        ),
        ComparisonRule(
            key="income_payslip_vs_employer",
            description="The payslip's net pay must match the employer-confirmed monthly net income.",
            topic=income,
            left=s("payslip", "net_pay.amount", "net_pay.currency", ["employee_name"]),
            right=s("employer_confirmation", "monthly_net_income.amount", "monthly_net_income.currency", ["employee_name"]),
            operator="numeric",
            # One month's pay vs a monthly average: the parser stays "uncertain" even on
            # matching values, so this pair informs the reviewer without blocking completion.
            mandatory=False,
        ),
        ComparisonRule(
            key="employer_payslip_vs_confirmation",
            description="The employer on the payslip and on the employer confirmation must be the same company.",
            topic="Legal name of the employer",
            left=s("payslip", "employer.name"),
            right=s("employer_confirmation", "employer.name"),
            operator="semantic",
        ),
        ComparisonRule(
            key="birth_number_contract_vs_tax",
            description="The tax certificate must belong to the borrower: same birth number as the contract.",
            topic="Czech birth number (rodné číslo) of the same person; a CZ prefix, slash or spaces are only formatting",
            left=s("loan_contract", "borrower_identifier"),
            right=s("tax_clearance_certificate", "tax_identifier"),
            operator="semantic",
        ),
        ComparisonRule(
            key="address_contract_vs_proof",
            description="The borrower's address in the contract must match the proof of address.",
            topic="Street and house number of the borrower's residential address",
            left=s("loan_contract", "borrower_address.address_line_1"),
            right=s("utility_bill", "service_address.address_line_1"),
            operator="semantic",
            when_both_present=True,
        ),
    ]
    definition["comparisons"] = definition["comparisons"] + [r.model_dump() for r in rules]
    definition["description"] = (
        "Illustrative salaried-loan evidence policy with cited cross-document consistency: "
        "income across contract, payslip and employer confirmation; employer; birth number on "
        "the employer confirmation and tax certificate; address. Completion is never credit "
        "approval; thresholds require business approval before production use."
    )
    return DocumentSet.model_validate(definition)
