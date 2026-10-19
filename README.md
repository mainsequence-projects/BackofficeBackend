# Back Office backend

Document reconciliation contracts and persistence on the Main Sequence platform.
Pydantic defines document attributes and form schemas. Main Sequence MetaTables
own application storage. The planned reconciliation agent uses `ms-tau-sdk`.

Implemented:

- Ten documented document models, recursive drafts, and JSON Schema export.
- Person profiles, versioned document sets, assignments, raw-source references,
  and revision-specific reviews with derived read-only acceptance.
- Sixteen documented MetaTable declarations, a frozen initial migration, and an
  explicit Main Sequence migration Job entry point.
- People, assignments, bounded raw-source uploads, versioned drafts/submission,
  authorized reviews, reconciliation findings, audit history and durable retry recovery.
- An illustrative `new_account_requirements` policy and offline contract/HTTP tests.

The business API is implemented and verified against local Main Sequence MetaTables.
Ten read-only MCP queries are implemented at `/mcp`; the remaining MCP commands
and the Tau agent remain separate milestones. The deployment workflow
gates the API on its explicit migration Job; hosted activation is verified separately.

## Development

Use Python 3.13+ and the committed dependency lock:

```bash
uv sync --locked
uv run metatables copy-metatables-skills --path .
uv run pytest -q
uv run ruff check src/backoffice api scripts tests
uv run ruff format --check src/backoffice api scripts tests
uv run python -m scripts.export_contracts --check
```

After editing models or table metadata, regenerate the artifacts:

```bash
uv run python -m scripts.export_contracts
```

The companion static-site repository provides **Back Office: local stack** in
VS Code. Its launcher starts local MetaTables, explicitly applies local migrations,
and runs this API through [scripts/local_api.py](scripts/local_api.py). The local
worker and developer-session adapters remain outside deployable `api/` entry points.

## Documentation

- [ADR 0001: Back Office helper, full MCP surface and document processing](docs/adr/0001-back-office-helper-mcp-and-document-processing.md)
- [ADR 0002: Automatic deployment of the agent using only MCP tools](docs/adr/0002-automatic-deployment-of-mcp-only-helper-agent.md)
- [Business API, permissions and operational contracts](docs/api.md)
- [Implemented MCP query tools and missing requirements](docs/mcp.md)
- [Namespace creation, workload roles and deployment](docs/namespace-workflow.md)
- [Foundation implementation and migration guide](docs/foundation.md)
- [Generated model reference](docs/model-reference.md)
- [Generated MetaTable dictionary](docs/metatable-dictionary.md)
- [Accepted project plan and target folders](docs/project-plan.md)
- [Business document catalog and intended checks](docs/document-catalog.md)
- [Main Sequence, API, MCP, and Tau contracts](docs/platform-contracts.md)

The companion `backofficefrontend` repository owns the Command Center application,
agent chat integration, and user guide. It consumes the documented business API.

## API discovery

The business [api/app/main.py](api/app/main.py) retains Main Sequence request identity.
Deployable FastAPI applications stay at `api/<name>/main.py` so CodeRepository
resource discovery can identify their entry points. Importing models, exporting
schemas, and starting this API do not migrate tables.
