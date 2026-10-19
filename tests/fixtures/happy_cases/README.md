# Authoritative happy-case inputs

The project owner specified that happy cases determine which document fields may
be obligatory. These files are exact copies of Parsing Motor's three named happy
packages' ground truth. `sources.json` records their original locations and byte
hashes. Keep them independent of generated Back Office schemas.

`tests/happy_cases.py` maps the source's ID card, bank statement and tax-certificate
fields into canonical payloads. Mapping joins name parts, wraps account holders in
a list, builds the explicit reporting period and translates `has_tax_arrears`.
It adds no issuing country, validity classification, bank name, account currency
or duplicate tax wording absent from `expected_fields`. The originals can print
extra details; these are optional extraction facts, not additional obligatory fields.
The bank's optional closing-balance number is not converted into a `Money` object
without an established currency, and salary credit has no standalone canonical
field. Neither omission is a rule for discarding production extraction data.

For the four types outside these packages, the project owner explicitly confirmed
the existing `tests/fixtures/documents/passport.json`, `employment_contract.json`,
`tax_return.json` and `source_of_funds_evidence.json` examples as authoritative.
Tests load those complete examples unchanged. Their existing obligatory fields
are all supported; no new schema version is necessary for those four types.

Update this evidence deliberately when the accepted happy cases change. Do not
add fabricated facts just to make a new schema's requirements pass.
