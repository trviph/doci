# AGENTS.md

Guidance for AI coding agents working in this repository. (`CLAUDE.md` points here.)

## What this is

DocI ("Document Intelligent engine") is an agentic document-processing service. It ingests documents (PDF / image), **mines** them (split → OCR/extract → annotate facts → classify against a dossier), then **audits** the mined facts against rules using LLM deep-agents, producing findings and a verdict. Built on FastAPI + TaskIQ + LangGraph + deepagents, backed by Postgres, S3/MinIO, and Valkey/Redis.

## Commands

Python 3.14, managed with `uv` (see `.tool-versions`: uv 0.11.1, atlas 1.2.1).

```bash
# Run everything in one process (API + in-process worker + scheduler + monitor) — dev default
uv run doci-all-in-one        # API :8000, monitor :8001 (PORT/MON_PORT env-driven)

# Or run the processes separately (production shape)
uv run doci-api               # FastAPI app only
uv run doci-worker            # TaskIQ worker (executes tasks)
uv run doci-scheduler         # TaskIQ scheduler (kicks cron maintenance tasks)
uv run doci-worker-mon        # dev task monitor (/tasks)

# Tests (pytest, configured in pyproject.toml; testpaths=tests)
uv run pytest                 # all
uv run pytest tests/tools/test_parse_money.py          # one file
uv run pytest tests/tools/test_parse_money.py::test_x  # one test

# Lint
uv run ruff check .
uv run ruff format .

# Backing services (Postgres :5432, MinIO :9000/:9001, Valkey :6379, Phoenix, vLLM)
docker compose -f docker/compose.yml up

# Migrations (Atlas; DATABASE_URL must be set)
make atlas-new name=add_something    # create a migration
make atlas-migrate                   # apply (atlas migrate apply)
make atlas-hash                      # rehash after editing migration files
```

There is no `.env` auto-loading — export env yourself (`set -a; . ./.env; set +a`). Copy `.env.sample` to `.env`; local defaults match `docker/compose.yml` (pg creds doci/doci, MinIO doci/doci12345).

## Architecture

### Process model
The same FastAPI app factory (`doci.api.create_app`) is reused by every deployment entrypoint in `commands/`. The API and the worker are separate processes in production but share **identical client wiring** via `doci.bootstrap.build_clients()` → a frozen `Clients` dataclass (Postgres, ObjStore, KV, MediaService, DocumentService, the workflow services, the userdata services, AuditService). Keep these two in sync — that's the whole point of `bootstrap.py`.

- **API** builds clients in the FastAPI lifespan, stashes them on `app.state`.
- **Worker** has no lifespan: it builds the same clients + the Valkey checkpointer once on `WORKER_STARTUP` and stashes them on `broker.state`; tasks read them via `doci.workflows.runtime.get_clients()` / `get_saver()`.

**Import order is load-bearing** in every entrypoint: `import doci.telemetry` must come *before* `doci.taskiq`, because telemetry installs `TaskiqInstrumentor` (which wraps `AsyncBroker.__init__`) and must be active before the broker is constructed. Task modules (`doci.workflows.*.task`, `doci.scheduler.tasks`) are imported for their import side-effect — registering `@broker.task` and event handlers.

### Job flow (mining → audit)
1. `POST /documents` → presigned S3/MinIO upload URL. Client PUTs bytes. `POST /documents/{id}/finalize` marks it READY and sets page_count.
2. `POST /workflows {document_id, workflow:"document_mining", dossier_key?}` enqueues a TaskIQ job and writes a `workflow_execution` row. Returns `{execution_id, task_id}`.
3. The mining task (`langgraph_document_mining/task.py`) runs a LangGraph graph: `finalize` (classify by type) → conditional route to the **pdf** or **image** child subgraph (or `unsupported`). PDF branch splits pages and fans out per-page extract/annotate/thumbnail (`DOCI_PDF_PAGE_CONCURRENCY`).
4. Passing `dossier_key` drives per-page classification AND **auto-chains an audit** on mining success (`enqueue_audit`). `job_id == document_id` ties the mining run and its audit together across all spans.
5. The audit task runs a 2-node graph `find → verdict` (`langgraph_audit/`), each node wrapping a deepagents deep-agent. Results land in `audit_findings`; query `GET /audits/{audit_eid}`.

### LangGraph workflows (`doci/workflows/`)
Graphs are built with **pure dependency injection** — builders take already-constructed activities + compiled child graphs, never reach for globals. Child graphs (image, pdf) are compiled **without their own checkpointer** and embedded as subgraph nodes so the *parent's* checkpointer persists their state. Durability uses a custom Valkey-backed `ValkeySaver` (`checkpoint.py`, Redis db 2, every key TTL'd so abandoned runs self-expire); the per-execution `thread_id` is the LangGraph thread.

### Agents & tools (`doci/agents/`, `doci/tools/`)
Audit agents are `deepagents` deep-agents. The orchestrator (`audit_orchestrator.py`) records findings and delegates rules to a `rule_auditor` subagent; `audit_verdict.py` concludes. Tools are **not all handed to the model at once**: each tool has a `build_*` factory bound to the run's execution ids/dossier/document, registered in a `ToolRegistry` with discovery tags. The agent uses the `find_tools` tool to search the registry by keyword, then the graph binds only the selected tools. Prompts live as markdown in `doci/prompts/` loaded via `doci.prompts.load`.

### LLM config (`doci/llm/config.py`)
Per-task, three-level env resolution: `DOCI_LLM_<TASK>_<FIELD>` → `DOCI_LLM_<FIELD>` → per-task code default. Tasks set their own MODEL/MAX_TOKENS in code (e.g. mining annotation defaults to `gpt-5-nano`, audit to `gpt-5-mini`) while shared gateway creds (BASE_URL/API_KEY) are set once. Models are `"provider:model"` strings for LangChain `init_chat_model`.

### Persistence
- **Postgres** — schema via **Atlas** versioned migrations in `migrations/` (NOT an ORM auto-migrate). Key tables: `media`, `document` / `document_part`, `workflow_execution`, `workflow_result` (mined output keyed by `(execution_id, part_id)`; kind `extract.md` = OCR text, `annotation.json` = facts), `audit_findings`, and the `userdata` tables (dossiers, document defs, agent rules, knowledge).
- **S3/MinIO** (`doci/objstore`) — raw media + thumbnails, accessed via presigned URLs.
- **Valkey/Redis** — three logical dbs: db 0 KV cache (`doci:` prefix), db 1 TaskIQ broker/results, db 2 LangGraph checkpoints.

### Telemetry
OpenTelemetry throughout (FastAPI, botocore, psycopg2, redis, taskiq auto-instrumented; LangChain via openinference). Phoenix is the local trace UI (`compose.phoenix.yml`). `DOCI_LLM_TRACE_CONTENT=false` by default — raw prompts/responses (incl. base64 images, PII) are NOT captured unless enabled; token/model/timing always are.

## Conventions

- **`@internal` boundary**: an `HttpRequestContextMiddleware` flags HTTP scopes so service methods decorated `@internal` refuse to run during a request (leaks surface as 403, not 500). Don't call internal/worker-only methods from request handlers.
- Routers follow a bind-or-resolve pattern: `build_*_router()` either takes a service or resolves it from `request.app.state` at request time.
- `userdata/<thing>/` and each workflow follow the same `models.py` / `service.py` / `router.py` (+ `task.py`/`graph.py`/`nodes/` for workflows) layout. Match the neighbouring module when adding code.
- Python 3.14: `except A, B:` (no parens) is valid PEP 758 syntax used in this repo — don't "fix" it.
- The user wants a git commit at each logical checkpoint, made *before* moving on (not batched). Stage files explicitly; don't sweep unrelated working-tree changes into a commit. Branch off `main` first.
