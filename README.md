# Back Office backend

Document reconciliation contracts and persistence on the Main Sequence platform.
Pydantic defines document attributes and form schemas. Main Sequence MetaTables
own application storage. The planned reconciliation agent uses `ms-tau-sdk`.

Implemented in this foundation:

- Ten documented document models, recursive drafts, and JSON Schema export.
- Person profiles, versioned document sets, assignments, raw-source references,
  and revision-specific reviews with derived read-only acceptance.
- Sixteen documented MetaTable declarations, a frozen initial migration, and an
  explicit Main Sequence migration Job entry point.
- An illustrative `new_account_requirements` policy and offline contract tests.

The business API, MCP tools, upload service, evaluator, Tau agent, and hosted
migration are subsequent milestones. The existing API remains starter code.

## Development

Use Python 3.13+ and the committed dependency lock:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check src/backoffice scripts tests
uv run ruff format --check src/backoffice scripts tests
uv run python -m scripts.export_contracts --check
```

After editing models or table metadata, regenerate the artifacts:

```bash
uv run python -m scripts.export_contracts
```

## Documentation

- [Foundation implementation and migration guide](docs/foundation.md)
- [Generated model reference](docs/model-reference.md)
- [Generated MetaTable dictionary](docs/metatable-dictionary.md)
- [Accepted project plan and target folders](docs/project-plan.md)
- [Business document catalog and intended checks](docs/document-catalog.md)
- [Main Sequence, API, MCP, and Tau contracts](docs/platform-contracts.md)

The companion `backofficefrontend` repository owns the Command Center application,
agent chat integration, and user guide. Its current contribution is the implementation plan.

## API discovery

The starter [api/app/main.py](api/app/main.py) retains Main Sequence request identity.
Deployable FastAPI applications stay at `api/<name>/main.py` so CodeRepository
resource discovery can identify their entry points. Importing models, exporting
schemas, and starting this API do not migrate tables.
