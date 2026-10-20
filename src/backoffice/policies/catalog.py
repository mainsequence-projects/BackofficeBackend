"""One policy catalog for publication, readiness and generated contracts."""

from ..models.document_set import DocumentSet
from .loan_requirements import loan_requirements
from .new_account_requirements import new_account_requirements
from .new_account_requirements import policy_definition as legacy_definition


def document_set_catalog() -> tuple[DocumentSet, ...]:
    """Return fresh definitions so callers cannot mutate a shared published policy."""
    return (
        new_account_requirements(1),
        new_account_requirements(2),
        loan_requirements(1),
        new_account_requirements(3),
        loan_requirements(2),
        new_account_requirements(4),
        loan_requirements(3),
        new_account_requirements(5),
        loan_requirements(4),
        new_account_requirements(6),
        loan_requirements(5),
        loan_requirements(6),
        new_account_requirements(7),
    )


def policy_definition(policy: DocumentSet) -> dict:
    """Retain the already-published account-opening JSON byte-for-byte in meaning."""
    if policy.key == "new_account_requirements" and policy.version == 1:
        return legacy_definition(policy)
    definition = policy.model_dump(mode="json")
    if not policy.comparisons:
        definition.pop("comparisons", None)
    return definition
