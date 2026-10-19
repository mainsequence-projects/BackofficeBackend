"""Published policy contracts cannot follow a growing document registry."""

import json
from pathlib import Path

import pytest

from src.backoffice.policies import loan_requirements, new_account_requirements, policy_definition

SNAPSHOTS = Path(__file__).resolve().parents[1] / "fixtures/published_policies"


@pytest.mark.parametrize("policy", [new_account_requirements(4), loan_requirements(3)])
def test_published_schema_pins_match_preserved_definitions(policy):
    expected = json.loads((SNAPSHOTS / f"{policy.key}.v{policy.version}.json").read_text())
    assert policy_definition(policy) == expected


@pytest.mark.parametrize(
    "factory,previous,current",
    [(new_account_requirements, 4, 5), (loan_requirements, 3, 4)],
)
def test_new_policy_only_changes_version_and_schema_pins(factory, previous, current):
    old = policy_definition(factory(previous))
    new = policy_definition(factory(current))
    new["version"] = old["version"]
    for old_requirement, new_requirement in zip(
        old["requirements"], new["requirements"], strict=True
    ):
        for old_option, new_option in zip(
            old_requirement["options"], new_requirement["options"], strict=True
        ):
            new_option["schema_version"] = old_option["schema_version"]
    for old_comparison, new_comparison in zip(old["comparisons"], new["comparisons"], strict=True):
        for side in ("left", "right"):
            new_comparison[side]["schema_version"] = old_comparison[side]["schema_version"]
    assert new == old


def test_policy_factory_returns_fresh_pins():
    policy = new_account_requirements(4)
    policy.requirements[0].options[0].schema_version = 2
    assert new_account_requirements(4).requirements[0].options[0].schema_version == 1
