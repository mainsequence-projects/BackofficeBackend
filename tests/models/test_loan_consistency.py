"""loan_requirements v6: v5 coverage plus cross-document consistency with existing operators."""

from src.backoffice.policies import document_set_catalog, policy_definition
from src.backoffice.policies.loan_requirements import loan_requirements


def test_v6_adds_consistency_rules_without_changing_v5():
    v5, v6 = loan_requirements(5), loan_requirements(6)
    assert v6.requirements == v5.requirements
    keys = [c.key for c in v6.comparisons]
    assert keys[0] == "monthly_net_income_consistency"            # v5's rule kept as is
    assert {"income_contract_vs_payslip", "income_payslip_vs_employer", "employer_payslip_vs_confirmation",
            "birth_number_contract_vs_employer", "birth_number_contract_vs_tax",
            "address_contract_vs_proof"} <= set(keys)
    pinned = {(o.document_type, o.schema_version) for r in v5.requirements for o in r.options}
    for rule in v6.comparisons:
        for side in (rule.left, rule.right):
            assert (side.document_type, side.schema_version) in pinned, rule.key
    assert policy_definition(loan_requirements(5)) == policy_definition(v5)


def test_v6_is_the_newest_published_loan_version():
    loans = [p.version for p in document_set_catalog() if p.key == "loan_requirements"]
    assert loans[-1] == 6 and loans == sorted(loans)
