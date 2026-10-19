"""Authority for the seven remaining types, independent of Pydantic field metadata.

Package expected_fields are the authoritative extraction facts. The four document
JSON examples without package sources were explicitly confirmed by the user.
Mappings rename/combine source fields but never add guessed country, validity,
account currency, bank name or duplicate tax-statement text.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures"
EXAMPLE_TYPES = ("passport", "employment_contract", "tax_return", "source_of_funds_evidence")


def load_happy_cases():
    cases = []
    for source in json.loads((ROOT / "happy_cases/sources.json").read_text()):
        fixture = "happy_cases/" + source["fixture"]
        expected = json.loads((ROOT / fixture).read_text())["expected_fields"]
        if "id_card" in expected:
            fields = expected["id_card"]
            cases.append(
                (
                    fixture + ":id_card",
                    {
                        "document_type": "national_identity_card",
                        "full_name": fields["first_name"] + " " + fields["last_name"],
                        "given_names": fields["first_name"],
                        "last_name": fields["last_name"],
                        "date_of_birth": fields["birth_date"],
                        "identity_number": fields["document_number"],
                        "expiration_date": fields["expiry_date"],
                    },
                )
            )
        if "bank_statement" in expected:
            fields = expected["bank_statement"]
            cases.append(
                (
                    fixture + ":bank_statement",
                    {
                        "document_type": "bank_statement",
                        "account_holders": [fields["account_holder"]],
                        "account_identifier": fields["iban"],
                        "statement_period": {
                            "start_date": fields["period_from"],
                            "end_date": fields["period_to"],
                        },
                        # Salary credit has no standalone canonical field; closing_balance
                        # cannot become Money without a separately established currency.
                        # Neither optional fact may justify fabricating a currency here.
                    },
                )
            )
        if "tax_or_debt_certificate" in expected:
            fields = expected["tax_or_debt_certificate"]
            cases.append(
                (
                    fixture + ":tax_or_debt_certificate",
                    {
                        "document_type": "tax_clearance_certificate",
                        "taxpayer_name": fields["holder_name"],
                        "tax_identifier": fields["birth_number"],
                        "issuing_authority": fields["tax_office"],
                        "certificate_number": fields["certificate_number"],
                        "issue_date": fields["issue_date"],
                        "arrears_statement": {"no": "no_arrears", "yes": "arrears_reported"}[
                            fields["has_tax_arrears"]
                        ],
                    },
                )
            )
    for kind in EXAMPLE_TYPES:
        fixture = f"documents/{kind}.json"
        cases.append((fixture, json.loads((ROOT / fixture).read_text())))
    return cases
