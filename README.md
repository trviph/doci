# Doci

> [!NOTE]
> **Archived: This repository is no longer maintained.**
> Doci was built as a demo to test automated financial auditing for a client. We discovered that real-world needs are far more complex than this initial architecture could support. While the core idea—using AI agents to extract data from documents and audit them against rules and smarter agents—is still valid, the system is being redesigned from scratch.
> *This code is left here as a historical reference, not as a foundation for new projects.*

## Why it's archived (The 6 Open Problems)

Building this demo revealed six major challenges. Any future version of this tool must solve these problems:

* **Relevancy:** How do we confirm a document is actually related to the task at hand?
* **Understanding:** How do we accurately pull meaning from messy files (like images or charts) and check it against strict rules?
* **Trust:** How do we guarantee the AI gives consistent, reliable answers every time?
* **Evaluation:** How can we quickly and cheaply test if changing a prompt made the system better or worse?
* **Scale:** How do we support many different use cases without making the system too bloated or fragile?
* **Cost:** Is the cost of running the AI worth it compared to hiring a human auditor?

---

Document Intelligent engine in an agentic era.

Doci is an agentic document-processing service. It **mines** documents (split → OCR/extract → annotate facts → classify each page against a *dossier*) and then **audits** the mined facts against rules using LLM deep-agents, producing structured **findings** and a **verdict**.

It's built on **FastAPI** (HTTP API), **TaskIQ** (durable background jobs), **LangGraph** (workflow orchestration), and **deepagents** (the audit agents), backed by **Postgres**, **S3/RustFS**, and **Valkey/Redis**.

## Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.14 | runtime (uses PEP 758 syntax) |
| [uv](https://docs.astral.sh/uv/) | 0.11.1 | dependency & script management |
| [Atlas](https://atlasgo.io/) | 1.2.1 | Postgres schema migrations |
| Docker | — | local backing services |

Backing services (run locally via Docker Compose): **Postgres**, **S3/RustFS**, **Valkey/Redis**. Exact pins live in [`.tool-versions`](./.tool-versions) and [`pyproject.toml`](./pyproject.toml).

## Quick start

```bash
# 1. Configure environment (the app does NOT auto-load .env)
cp .env.sample .env
set -a; . ./.env; set +a          # export it into your shell

# 2. Bring up backing services (Postgres :5432, RustFS :9000/:9001, Valkey :6379, Langfuse :3000, vLLM)
docker compose -f docker/compose.yml up -d

# 3. Apply database migrations (DATABASE_URL must be set)
make atlas-migrate

# 4. Run everything in one process: API + in-process worker + scheduler + monitor
uv run doci-all-in-one
```

The API serves on `:8000` and the dev task monitor on `:8001` (both env-driven via `PORT` / `MON_PORT`). Local defaults in `.env.sample` match `docker/compose.yml` (Postgres `doci/doci`, RustFS `doci/doci12345`).

## Architecture (in brief)

A single FastAPI app factory (`doci.api.create_app`) is reused by every entrypoint in `commands/`. The **API** and the **worker** are separate processes in production but share identical client wiring via `doci.bootstrap.build_clients()`, so they stay in sync.

The core pipeline is **mining → audit**:

1. A document is uploaded, finalized, then submitted to the `document_mining` workflow.
2. Mining runs a LangGraph graph: classify the document, then route to the **PDF** or **image** child subgraph (split → per-page extract / annotate / thumbnail).
3. If a `dossier_key` is supplied, each page is classified against that dossier's document types **and** an **audit** is auto-chained on mining success.
4. The audit runs a `find → verdict` graph, each node a deepagents deep-agent that investigates rules and concludes with a verdict + findings.

Persistence splits across three stores:

- **Postgres** — schema managed by **Atlas** versioned migrations (`migrations/`), *not* an ORM auto-migrate. Holds documents, workflow executions, mined results, and audit findings.
- **S3/RustFS** — raw media and thumbnails, accessed via presigned URLs.
- **Valkey/Redis** — three logical dbs: `0` KV cache, `1` TaskIQ broker/results, `2` LangGraph checkpoints.

## End-to-end usage

The HTTP flow to mine and audit a document (API base = the `doci-api` app; task status = the monitor app):

```bash
# 1. Create a document → returns {id, upload_url} (presigned S3/RustFS PUT)
POST /documents            {"name": "invoice.pdf"}

# 2. Upload the bytes to the presigned URL
PUT  <upload_url>          <file bytes>

# 3. Finalize → marks the document READY, sets page_count
POST /documents/{id}/finalize

# 4. Submit the mining workflow (dossier_key drives per-page classification
#    AND auto-chains the audit on success) → returns {execution_id, task_id}
POST /workflows            {"document_id": "...", "workflow": "document_mining", "dossier_key": "phap-ly-thue"}

# 5. Poll the monitor app until the task is done
GET  /tasks/{task_id}      # state: success | failure | ...

# 6. Read the audit result (find the auto-chained audit execution id via the monitor)
GET  /audits/{audit_eid}   # status, verdict, rationale, findings[]
```

## Deployment shapes

- **Dev / single-node:** `uv run doci-all-in-one` — API, an in-process TaskIQ worker, the scheduler, and the monitor all in one asyncio loop.
- **Production:** run the processes separately —

  | Command | Role |
  |---------|------|
  | `uv run doci-api` | FastAPI HTTP app |
  | `uv run doci-worker` | TaskIQ worker (executes jobs) |
  | `uv run doci-scheduler` | TaskIQ scheduler (cron maintenance tasks) |
  | `uv run doci-worker-mon` | dev/ops task monitor (`/tasks`) |

## Development

```bash
# Tests (pytest; testpaths=tests)
uv run pytest                                              # all
uv run pytest tests/tools/test_parse_money.py             # one file
uv run pytest tests/tools/test_parse_money.py::test_name  # one test

# Lint & format
uv run ruff check .
uv run ruff format .

# Migrations (Atlas)
make atlas-new name=add_something    # create a new migration file
make atlas-migrate                   # apply pending migrations (needs DATABASE_URL)
make atlas-hash                      # rehash after hand-editing migration files
```

This repo targets Python 3.14 and uses PEP 758 syntax (e.g. `except A, B:` without parentheses) — that's valid, not a bug.

## Configuration

[`.env.sample`](./.env.sample) is the source of truth for every setting, with inline docs and local defaults. A couple of things worth knowing:

- **Per-task LLM config** resolves per field in three levels: `DOCI_LLM_<TASK>_<FIELD>` → `DOCI_LLM_<FIELD>` → per-task code default. So each task (e.g. `ANNOTATE_TEXT`, `EXTRACT_IMAGE`, `AUDIT`) picks its own model while shared gateway credentials are set once. Models are `"provider:model"` strings.
- **`DOCI_LLM_TRACE_CONTENT` defaults to `false`** — raw prompts/responses (which can include base64 images and PII) are *not* captured in traces unless you opt in. Token/model/timing are always traced.

## Project layout

| Path | Contents |
|------|----------|
| `doci/` | the application package |
| `commands/` | deployment entrypoints (`api`, `worker`, `scheduler`, `worker_mon`, `all_in_one`) |
| `migrations/` | Atlas versioned SQL migrations |
| `docker/` | Compose files + Dockerfiles for the stack |
| `tests/` | pytest suite |

Notable `doci/` subpackages:

| Package | Role |
|---------|------|
| `activities/` | pure units of work (split, extract, annotate, thumbnail, …) |
| `workflows/` | LangGraph graphs + TaskIQ tasks (document mining, audit) |
| `agents/` | deepagents deep-agent definitions (audit orchestrator, rule auditor, verdict) |
| `tools/` | agent tools + a discovery registry (`find_tools`) |
| `audit/` | audit findings model + service |
| `userdata/` | dossiers, document defs, agent rules, knowledge |
| `bootstrap.py` | shared client wiring used by both API and worker |

## Telemetry

OpenTelemetry instruments the whole stack (FastAPI, botocore, psycopg2, redis, TaskIQ, and LangChain via openinference). [Langfuse](https://langfuse.com/) runs as the local trace UI at [http://localhost:3000](http://localhost:3000) — a self-contained multi-service stack (web + worker + Postgres + ClickHouse + Redis + an S3 blob store) defined in `docker/compose.langfuse.yml`. It ingests **traces only**, over OTLP/HTTP with Basic auth; enable it by uncommenting the `OTEL_EXPORTER_OTLP_*` block in `.env.sample` (which sets `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` and turns metrics/logs export off, since Langfuse accepts traces only).
