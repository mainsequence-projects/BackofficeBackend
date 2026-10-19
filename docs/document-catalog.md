# Document model and field catalog

This is the accepted business field catalog and intended reconciliation behavior.

V1 reconciles document facts. Portrait references, photo-presence checks and face
comparison are deferred to [product V2 scope](project-plan.md#product-v1-scope-and-v2-follow-up).
Current identity-card schema 3 and passport schema 2 contain no portrait field.
All document forms also omit that section for historical schemas. Original source
files and retained historical revisions remain unchanged.

## Required-field audit (2026-10-19)

The minimum below is for a completed canonical payload, not a decision that a
case is complete. Optional source facts remain null when absent; a document-set
policy can require them for a particular use. Names, identifiers, primary amounts
and reporting periods remain required where they identify the subject and the
evidence being supplied. Nested amounts still need currency; supplied periods
still need both endpoints.

Happy cases are authoritative for obligatory fields, as confirmed by the project
owner. A field absent from the authoritative happy-case extraction must not be
mandatory just because the previous model required it. Presence in an example
does not by itself make an already optional field mandatory.

All 13 types were reviewed against their canonical fixtures. The Parsing Motor
`01_happy_all7_A`, `02_happy_all7_B` and `12_happy_5types_B` examples and their
source generator supply additional examples for the seven loan-related types.
The source generator matters: its payslips print gross pay although the
ground-truth comparison field list omits it. That list is not the complete source.
Its identity cards do not print issue dates; the current ID model already permits
both omission and null. Its address layout A does not state a utility category,
so the model must not force extraction to guess one from the issuer.

The second pass explicitly anchors the remaining seven types in independent
happy-case inputs:

- National ID, bank statement and tax certificate use the packages' `expected_fields`
  as the authoritative extraction facts. Source PDFs can contain additional
  information, such as bank names and verbatim tax wording; extracting those
  details remains useful but is not a completion requirement. IDs need no separate
  issuing-country or validity-classification value; statements need no bank name
  or separate account currency; certificates need no duplicate verbatim statement.
- Passport, employment contract, tax return and source-of-funds evidence use the
  existing `tests/fixtures/documents/*.json` examples, explicitly confirmed by the
  project owner. Each example supplies its existing required fields, including
  conditional salary information where applicable. Those four schemas therefore
  need no further relaxation; this is now tested against the complete examples,
  rather than relying on the models to justify themselves.

Self-contained copies of the package ground truth, with source paths and SHA-256
hashes, are in `tests/fixtures/happy_cases/`. `tests/happy_cases.py` maps their
original names to canonical fields without adding guessed data. All twelve mapped
examples across the seven types must pass canonical validation and real API
submission. This guards against reintroducing unsupported obligatory fields.

| Document type | Current schema | Required source facts | Optional details / decision |
| --- | --- | --- | --- |
| National identity card | 3 | Full name, birth date, identity number | Issue date already optional. Issuing country and validity type are now optional. A printed expiry is usable without a separate validity classification; explicit fixed-term validity still requires expiry and permanent validity forbids it. No expiry and no permanent-validity evidence remains unknown to the policy. |
| Passport | 2 | Full name, birth date, passport number, nationality, issuing country, expiry | Issue date, separate name parts and MRZ remain optional; policies can require MRZ. |
| Residence permit | 2 | Full name, permit number, issuing country, validity type | Printed permit category is now optional; absence does not imply any entitlement. Conditional expiry remains enforced. |
| Utility bill | 2 | Account-holder name, service address, provider, issue date | Service category is now optional. Amount, account number and billing period remain optional for address evidence. Issue date remains the freshness anchor. |
| Bank statement | 2 | Account holders, account identifier, statement period | Bank name and separate account-level currency are now optional. Every supplied monetary amount still needs its own currency; balances must agree with the account currency when it is supplied. Separate issue date, address, balances and transactions remain optional. |
| Employment contract | 1 | Employee, employer, employment type, start date | Job title, signature date and salary already optional. Fixed-term end date and supplied salary's frequency/basis remain conditional requirements so terms are interpretable. |
| Payslip | 2 | Employee, employer, pay period, net pay with currency | Gross pay is now optional for net-income evidence; deductions remain optional. Currency agreement is checked for every supplied amount. |
| Tax return | 1 | Taxpayer, jurisdiction, fiscal period, declared income with currency | Tax identifier, taxable income, activity and filing details already optional. Filing evidence can still be requested separately. |
| Source-of-funds evidence | 1 | Owner, origin category, amount with currency, explanation | Event date, originating party and supporting links already optional; a policy may require substantiation. |
| KYC questionnaire | 2 | Full name, employment status, account purpose, expected monthly inflow with currency, sources of funds | Outflow estimate, completion instant and questionnaire version are now optional for external forms. Unknown outflow is not zero. An undated form cannot satisfy a policy requiring completion-date freshness. |
| Loan contract | 2 | Borrower, contract date, lender, principal with currency | Contract reference is now optional; income, address and printed evidence list already optional at schema level. The loan policy still requires declared net income. |
| Employer confirmation | 2 | Employee, employer, issue date, monthly net income with currency | Income basis is now nullable/optional; absence never implies single-month income. Employment dates, position and income period remain optional. This type remains an employment-and-income confirmation. |
| Tax clearance certificate | 2 | Taxpayer, issuing authority, issue date, arrears statement | Duplicate verbatim statement text is now optional. Identifier, certificate number, separate as-of date and arrears amount remain optional. Missing text or amount never implies tax clearance or zero debt. |

Version 1 schemas and historical policies remain unchanged. The nine relaxed
contracts are registered as version 2. New account policy 6 and loan policy 5 pin
the current schemas, including comparison selectors, while retaining validity,
freshness, income and review requirements. Existing cases keep their assigned
policy; adopting the new contracts requires an explicit policy upgrade. The explicit admin upgrade `POST /admin/persons/{uid}/happy-case-requirements`
accepts an idempotency `operation_key` and upgrades existing subject documents
and cases. It appends current-schema revisions with the same document facts and sources,
retains existing accepted/rejected decisions with provenance, and preserves all
original revisions. Obsolete portrait metadata is omitted from the new revisions;
original source attachments and historical portrait metadata remain retained.
The original parser observations retain their original schema hash and values. Unreviewed parser results are rechecked using their saved
classification score and the current acceptance policy. Manual drafts are not
automatically accepted. Cases adopt account policy 6 or loan policy 5; evaluations
must be rerun against the new versions. Repeating the operation is safe.
Missing optional attributes are advisory and do not change case completeness.

Account policy 4 and loan policy 3 retain their exact previously published schema
references. Their document pins are explicit: adding a newer document schema to
the registry must never change an existing policy definition. The newer policy
versions only update document-schema references; the business checks and comparison
tolerances are unchanged. Publishing the catalog adds missing versions and rejects
any attempted change to a published definition.

The parser selects the newest published schema for each type. The frontend also
selects the newest catalog version for manual document creation; editing an
existing document uses its recorded version. Version-1 API calls remain supported,
and legacy API defaults remain version 1; API clients must pass `schema_version=2`
when creating one of the relaxed types. Deployment must publish the new catalog through the existing migration
Job before readiness succeeds; no live catalog was modified by this code change.

The detailed tables below describe the preserved version-1 contracts. For current
version-2 field descriptions, use the generated [model reference](model-reference.md)
and the corresponding `v2.json` schemas. Minimal payload, null, validation and
submission regressions cover every document type in
`tests/models/test_document_minimums.py`, `tests/models/test_happy_case_contracts.py` and
`tests/api/test_minimal_document_workflows.py`.

The shared catalog also includes `loan_contract`, `employer_confirmation`, and
`tax_clearance_certificate` version 1. Their exact fields are in the generated
[model reference](model-reference.md); their policy scope and extraction contracts
are described in [Shared document engine](shared-document-engine.md). They use the
same submission, review and requirement services as all other document types.
The contracts are implemented; the [generated model reference](model-reference.md)
and [JSON Schemas](../schemas/documents/) are authoritative for current fields.
The checks described below include future reconciliation rules; the
[foundation guide](foundation.md) distinguishes implemented validators from those rules.

## Field conventions

- **R**: required in the completed canonical payload; missing values are allowed in a draft.
- **O**: may be omitted, with `default=None` unless a meaningful default is specified.
- **C**: required when the stated condition applies, checked by a model or policy rule.
- A document-set policy can require an optional field for a particular alternative.
- Missing, unreadable, absent from the source, and not applicable are separate evidence
  outcomes. Do not use an empty string or zero to represent an unknown value.
- All fields use `Field(description=..., title=...)`; include format, units, source
  location, examples, and relevant constraints. The descriptions below are the
  starting wording. Nested fields and system-managed fields also need descriptions.
- Identifiers are strings. Dates use ISO calendar dates; timestamps include a time
  zone and are stored in UTC. Amounts use `Decimal`, never floating-point values.
- Preserve original text and compare using derived normalized values. Names must
  support people with one name; do not require a surname universally.
- Fixed schema values such as `document_type` are read-only in generated forms.

## Shared models

| Model.field | Type | Required | Description |
| --- | --- | --- | --- |
| `PostalAddress.address_line_1` | `str` | R | Primary street, building, or locality line exactly as stated by the source. |
| `PostalAddress.address_line_2` | `str` | O | Additional unit, floor, building, or locality information. |
| `PostalAddress.city` | `str` | O | City or locality named in the address, when provided. |
| `PostalAddress.region` | `str` | O | State, province, or administrative region named in the address. |
| `PostalAddress.postal_code` | `str` | O | Postal code as printed, preserving letters, spaces, and leading zeros. |
| `PostalAddress.country_code` | `str` | O | ISO two-letter country code when the source or verified reference identifies the country; do not infer it silently. |
| `Money.amount` | `Decimal` | R | Monetary amount in the associated currency, preserving the source precision and sign. |
| `Money.currency` | `str` | R | ISO three-letter currency code for the monetary amount. |
| `DatePeriod.start_date` | `date` | R | First calendar date included in the reporting or payment period. |
| `DatePeriod.end_date` | `date` | R | Last calendar date included in the period; must not precede the start date. |
| `Employer.name` | `str` | R | Employer's legal or trading name exactly as printed. |
| `Employer.registration_number` | `str` | O | Employer registration identifier as printed, preserving formatting and leading zeros. |
| `Employer.address` | `PostalAddress` | O | Employer address stated in the document. |
| `BankTransaction.booking_date` | `date` | R | Date on which the bank records the transaction in the statement. |
| `BankTransaction.value_date` | `date` | O | Value date printed for the transaction, if distinct from booking date. |
| `BankTransaction.amount` | `Money` | R | Signed transaction amount; positive means credit and negative means debit from the account holder's perspective. |
| `BankTransaction.description` | `str` | O | Transaction narrative exactly as printed, before normalization. |
| `BankTransaction.counterparty_name` | `str` | O | Named payer or payee, when explicitly identified by the statement. |
| `EvidenceRegion.raw_document_uid` | `UUID` | R | UID of the immutable source document containing this evidence. |
| `EvidenceRegion.page_number` | `int` | R | One-based page number in the source; must be greater than zero. |
| `EvidenceRegion.bounding_box` | `list[float]` | O | Four normalized coordinates `[left, top, right, bottom]` within the upright page, each between zero and one. |

## National Identity Card

Model `NationalIdentityCard`; discriminator `national_identity_card`;
module `models/documents/national_identity_card.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `full_name` | `str` | R | Holder's complete name exactly as printed on the card. |
| `given_names` | `str` | O | All given names in their printed order when identified separately. |
| `last_name` | `str` | O | Surname or family name when identified separately on the card. |
| `date_of_birth` | `date` | R | Holder's printed date of birth, entered as YYYY-MM-DD. |
| `identity_number` | `str` | R | Identity identifier printed on the card, preserving letters and leading zeros. |
| `issuing_country` | `str` | R | Country or issuing authority identified on the card. |
| `issue_date` | `date` | O | Date the card was issued, if printed. |
| `validity_type` | `Literal['fixed_term','permanent','unknown']` | R | Whether the source states a fixed expiry, permanent validity, or does not establish validity. |
| `expiration_date` | `date` | C | Printed expiry date; required when validity is fixed-term. |

Checks: name and birth-date consistency, identifier presence and validity at
evaluation time. Unknown validity requires review. Portrait and face checks are V2 scope.

## Passport

Model `Passport`; discriminator `passport`; module `models/documents/passport.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `full_name` | `str` | R | Holder's complete name exactly as printed in the visual inspection zone. |
| `given_names` | `str` | O | All given names in their printed order, if separately identified. |
| `last_name` | `str` | O | Printed surname or family name, if separately identified. |
| `date_of_birth` | `date` | R | Holder's printed date of birth, entered as YYYY-MM-DD. |
| `passport_number` | `str` | R | Passport identifier exactly as printed, preserving letters and leading zeros. |
| `nationality` | `str` | R | Nationality exactly as stated by the passport; retain the original value. |
| `issuing_country` | `str` | R | Country or issuing authority identified on the passport. |
| `issue_date` | `date` | O | Date the passport was issued, if printed. |
| `expiration_date` | `date` | R | Printed passport expiry date, entered as YYYY-MM-DD. |
| `mrz_lines` | `list[str]` | O | MRZ lines in printed order, preserving every character including `<` fillers. |

Checks: identity, nationality, expiry, supported MRZ format/check digits, and MRZ
agreement with the visual zone. Additional issuing-document variants require an
explicit schema version rather than invented dates.

## Residence Permit

Model `ResidencePermit`; discriminator `residence_permit`;
module `models/documents/residence_permit.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `full_name` | `str` | R | Permit holder's complete name exactly as printed. |
| `date_of_birth` | `date` | O | Holder's printed date of birth, if present. |
| `permit_number` | `str` | R | Residence-permit identifier exactly as printed. |
| `issuing_country` | `str` | R | Country or authority that issued the residence permit. |
| `permit_type` | `str` | R | Printed permit category or class without inferring additional entitlements. |
| `residency_status` | `str` | O | Residency status explicitly stated by the source. |
| `issue_date` | `date` | O | Printed permit issue date. |
| `validity_type` | `Literal['fixed_term','permanent','unknown']` | R | Validity stated by the document; unknown when the source does not establish it. |
| `expiration_date` | `date` | C | Printed expiry date; required for fixed-term validity. |
| `conditions` | `list[str]` | O | Restrictions or conditions transcribed from the permit. |

Checks: holder consistency, applicable residency category, validity, and stated
conditions relevant to the configured policy.

## Utility Bill

Model `UtilityBill`; discriminator `utility_bill`;
module `models/documents/utility_bill.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `account_holder_name` | `str` | R | Customer or account-holder name printed on the bill. |
| `service_address` | `PostalAddress` | R | Address where the utility service is supplied, distinguished from a mailing address. |
| `provider_name` | `str` | R | Utility provider's name as printed. |
| `utility_type` | `str` | R | Type of service stated by the bill, such as electricity, water, gas, or telecommunications. |
| `issue_date` | `date` | R | Bill issue date used for the document-age check. |
| `billing_period` | `DatePeriod` | O | Service period covered by the bill, when printed. |
| `account_number` | `str` | O | Provider's customer/account identifier, preserving leading zeros. |
| `total_due` | `Money` | O | Total amount due as printed, if needed by the configured workflow. |

Checks: customer name, service-address consistency, accepted utility category,
and age measured from the issue date.

## Bank Statement

Model `BankStatement`; discriminator `bank_statement`;
module `models/documents/bank_statement.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `account_holders` | `list[str]` | R | One or more account-holder names exactly as printed, including joint holders. |
| `bank_name` | `str` | R | Institution issuing the statement. |
| `account_identifier` | `str` | R | Printed account number or IBAN; retain masking and leading zeros. |
| `holder_address` | `PostalAddress` | O | Account-holder address printed on the statement. |
| `statement_period` | `DatePeriod` | R | Inclusive reporting period covered by the statement. |
| `issue_date` | `date` | O | Statement issue date, if separately stated from the period end. |
| `currency` | `str` | R | ISO three-letter currency of the statement account. |
| `opening_balance` | `Money` | O | Account balance at the beginning of the stated reporting period. |
| `closing_balance` | `Money` | O | Account balance at the end of the stated reporting period. |
| `transactions` | `list[BankTransaction]` | O | Transcribed transactions; null means not extracted, while an empty list requires evidence of no transactions. |

Checks: ownership, optional address, coverage, deposits supporting income/funds,
and balance consistency only when transaction coverage is known to be complete.

## Employment Contract

Model `EmploymentContract`; discriminator `employment_contract`;
module `models/documents/employment_contract.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `employee_name` | `str` | R | Employee's complete name as stated in the contract. |
| `employer` | `Employer` | R | Employer identity and optional registration/address details stated in the contract. |
| `job_title` | `str` | O | Position or occupation named in the contract. |
| `employment_type` | `str` | R | Employment arrangement stated by the contract, such as permanent or fixed-term. |
| `start_date` | `date` | R | Contractual employment start date. |
| `end_date` | `date` | C | Contractual end date when a fixed term is stated. |
| `salary` | `Money` | O | Contractual salary amount in the stated currency and frequency. |
| `salary_frequency` | `str` | C | Period the salary covers, such as hourly, monthly, or annually; required when salary is supplied. |
| `salary_basis` | `Literal['gross','net','unspecified']` | C | Whether the stated salary is gross or net; required when salary is supplied. |
| `signed_date` | `date` | O | Signature date stated in the contract. |

Checks: person/employer match, dates, stated salary, and required signature
evidence. A contract alone does not establish that employment remains active today.

## Payslip

Model `Payslip`; discriminator `payslip`; module `models/documents/payslip.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `employee_name` | `str` | R | Employee name exactly as printed on the payslip. |
| `employer` | `Employer` | R | Employer identity stated by the payslip. |
| `pay_period` | `DatePeriod` | R | Inclusive employment/pay period represented by the payslip. |
| `payment_date` | `date` | O | Date on which payment is stated to occur. |
| `gross_pay` | `Money` | R | Total pay before deductions, in the stated currency. |
| `net_pay` | `Money` | R | Amount payable to the employee after deductions. |
| `deductions` | `Money` | O | Total deductions stated on the payslip; absence is not a zero deduction. |
| `employee_identifier` | `str` | O | Employer-assigned payroll identifier as printed. |

Checks: employee/employer agreement, distinct periods, salary consistency, currency,
and corresponding bank deposits. Apply arithmetic only when all relevant components
are known; allowances and adjustments can require additional detail.

## Tax Return

Model `TaxReturn`; discriminator `tax_return`;
module `models/documents/tax_return.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `taxpayer_name` | `str` | R | Taxpayer's full name exactly as stated in the return. |
| `tax_identifier` | `str` | O | Taxpayer identifier as printed, retaining masking and leading zeros. |
| `tax_jurisdiction` | `str` | R | Tax authority or jurisdiction to which the return relates. |
| `tax_period` | `DatePeriod` | R | Inclusive fiscal period covered by the return. |
| `declared_income` | `Money` | R | Total income declared for the stated period and currency. |
| `taxable_income` | `Money` | O | Income subject to taxation as stated by the return. |
| `economic_activity` | `str` | O | Occupation, business activity, or category explicitly declared in the return. |
| `filing_date` | `date` | O | Date of submission when established by the source. |
| `filing_reference` | `str` | O | Authority-issued submission/acknowledgment reference, when supplied. |

Checks: taxpayer match, period and currency, declared income against other evidence,
and filing evidence when required. An unsigned draft is distinguishable from proof
of filing through the source and review findings.

## Source-of-Funds Evidence

Model `SourceOfFundsEvidence`; discriminator `source_of_funds_evidence`;
module `models/documents/source_of_funds_evidence.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `owner_name` | `str` | R | Person or entity identified as the owner or recipient of the funds. |
| `source_type` | `str` | R | Stated origin category, such as salary, savings, asset sale, inheritance, gift, business income, or other. |
| `amount` | `Money` | R | Amount whose source is being explained, with its currency. |
| `event_date` | `date` | O | Date of the originating event or transfer, when stated. |
| `originator_name` | `str` | O | Named payer, donor, seller, estate, or other originating party. |
| `explanation` | `str` | R | Factual explanation connecting the originating event to the funds being assessed. |
| `supporting_document_ids` | `list[UUID]` | C | Linked evidence documents supporting the explanation; required for policies that request substantiation. |

Checks: ownership, links between event and transfer, amounts/currencies, chronology,
and supporting revisions. Pin supporting document revisions in evaluations. A
description or extracted claim alone does not establish legitimacy.

## KYC Questionnaire

Model `KYCQuestionnaire`; discriminator `kyc_questionnaire`;
module `models/documents/kyc_questionnaire.py`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `full_name` | `str` | R | Name supplied by the person completing the questionnaire. |
| `occupation` | `str` | O | Person's declared occupation or principal economic activity. |
| `employment_status` | `str` | R | Declared status, such as employed, self-employed, retired, student, or unemployed. |
| `account_purpose` | `str` | R | Person's explanation of the intended use of the account. |
| `expected_monthly_inflow` | `Money` | R | Expected total incoming funds per calendar month, with currency. |
| `expected_monthly_outflow` | `Money` | R | Expected total outgoing funds per calendar month, with currency. |
| `source_of_funds` | `list[str]` | R | One or more declared origins of the money expected to enter the account. |
| `completed_at` | `datetime` | R | Time the completed submission was recorded; generated by the server for in-application forms. |
| `questionnaire_version` | `str` | R | Version of the questionnaire presented to the person. |

Checks: required answers, nonnegative expected flows, and consistency with supporting
evidence. Preserve the exact submitted questionnaire as a raw-source snapshot.

## Envelope and provenance documentation

The common document envelope documents `uid`, `person_uid`, `schema_version`,
`revision`, `raw_document_refs`, `processing_status`, `review_status`, `accepted`,
and timestamps. Review records document the trusted actor, time, reason, decision,
and exact revision. Clients cannot set server-managed review fields by updating
document attributes.

Field evidence records its JSON field path, source UID, page/location, original
text, extraction method/version, time, and optional confidence. Confidence includes
its scale and producer and is never interpreted as proof of correctness. Corrections
retain provenance and the superseded value through revision history.

`Person` documents its UID, external reference, full/given/family names, date of
birth, nationalities, residential address, employment status, profile revision,
and timestamps. Reference fields can be incomplete while a case is being assembled;
the assigned policy determines which are required for evaluation.

## Definition of done for each document type

1. Implement its Pydantic model and discriminant with English descriptions on every field.
2. Add nested-field descriptions, field constraints, and conditional validators.
3. Register its canonical and draft schema versions.
4. Generate its form/schema documentation and publish the schema snapshot through MetaTables.
5. Add a valid synthetic example, an incomplete draft, and meaningful invalid examples.
6. Specify the deterministic checks and evidence needed for review.
7. Verify equivalent REST and MCP serialization and generated-form behavior.
8. Document the implemented upload/review workflow in the frontend's owning user-guide page.
