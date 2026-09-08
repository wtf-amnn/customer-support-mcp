# Customer Support Operations MCP Server

An MCP server that gives an LLM controlled, validated, auditable access to a relational customer-support system — customers, tickets, comments, and a knowledge base.

---

## Problem statement

Support work is spread across a ticketing system, customer records, and an internal knowledge base. Answering a single question — *"is this urgent, who should own it, and what does our policy say?"* — means reading from all three and then acting on the first.

An LLM is well suited to that reasoning, but not to being handed a database. Direct SQL access has no notion of which state transitions are legal, no validation of what a priority or status may be, no record of who changed what, and no guard on destructive operations. The model would be free to move a closed ticket back to open, invent a priority value, or delete a record without confirmation.

This server is the layer in between. Every action the model can take is an explicitly defined tool with a validated input schema, business rules enforced server-side, and an audit entry attributed to a named actor. The model gets enough access to be useful and no more.

---

## Overview

The server exposes a support-operations database over the Model Context Protocol, implementing all three MCP capabilities:

- **Tools** — 13 actions the model can call: customer and ticket CRUD, assignment, commenting, and validated status changes.
- **Resources** — 3 URI-addressed read-only views: a customer profile, an aggregated ticket dossier, and knowledge-base articles by category.
- **Prompts** — 2 reusable workflows that chain tools and context into a repeatable support procedure.

It runs over stdio (as a local subprocess, e.g. for Claude Desktop) or Streamable HTTP (as a standalone service).

---

## Architecture

The codebase is deliberately layered, and the direction of dependency only ever points downward:

```
MCP interface   (server.py)          tools, resources, prompts
      │
      ▼
Service layer   (services/)          business rules, audit logging
      │
      ▼
Schemas         (schemas.py)         Pydantic validation
      │
      ▼
Models          (models.py)          SQLAlchemy ORM, constraints
      │
      ▼
Database        (database.py)        engine, session lifecycle
```

The important property is that **the service layer has no knowledge of MCP**. `create_ticket()` is an ordinary Python function taking a validated Pydantic object and a database session. It can be called from a test, a CLI script, or a web API without change. `server.py` is a thin adapter that translates MCP tool calls into service calls and back into JSON.

This is why the seed scripts can reuse the exact same code paths the model uses — including audit logging — with no duplication.

**Validation happens twice, on purpose.** MCP generates an input schema from each tool's type hints, so the protocol layer guarantees `email` is a string. Pydantic then enforces that it is actually an email, that a priority is one of four values, and that a subject is within length limits. Type-correct and valid are different claims.

---

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.10+ |
| MCP | MCP Python SDK v2 (`MCPServer`) |
| ORM | SQLAlchemy 2.x (typed `Mapped[]` style) |
| Validation | Pydantic v2 |
| Database | SQLite |
| HTTP server | Uvicorn + Starlette (via the SDK) |
| Package manager | uv |

---

## Project structure

```
customer-support-mcp/
├── app/
│   ├── services/
│   │   ├── audit_service.py      # centralized audit logging
│   │   ├── customer_service.py   # customer CRUD + domain exceptions
│   │   └── ticket_service.py     # ticket lifecycle, state machine, comments
│   ├── context.py                # contextvar-based actor identity
│   ├── database.py               # engine, session factory, init_db
│   ├── models.py                 # SQLAlchemy models
│   ├── schemas.py                # Pydantic Create/Update/Read schemas
│   └── server.py                 # MCP tools, resources, prompts
├── tests/                        # (not yet implemented)
├── seed_articles.py              # knowledge-base seed data
├── seed_data.py                  # customers, tickets, comments seed data
├── migrate_add_actor.py          # one-off migration: audit_logs.actor
├── customer_support.db           # SQLite database (generated)
├── pyproject.toml
└── uv.lock
```

---

## Data model

Five tables:

**`customers`** — name, unique email, optional phone, status (`active` / `inactive`), timestamps.

**`tickets`** — belongs to a customer; subject, description, priority (`low` / `medium` / `high` / `urgent`), status (`open` / `in_progress` / `resolved` / `closed`), optional assigned team, timestamps. Indexed on `(status, priority)` since that is the most common query shape.

**`ticket_comments`** — belongs to a ticket; author, body, timestamp.

**`knowledge_articles`** — slug (unique, human-readable), title, category, body. Reference content, not operational state.

**`audit_logs`** — action, entity type, entity id, actor, JSON details, timestamp. Written for every mutating operation.

Relationships cascade: deleting a customer deletes their tickets, and deleting a ticket deletes its comments. Enum-like columns are guarded by `CheckConstraint`s at the database level in addition to Pydantic validation, so invalid values cannot be written even by code that bypasses the schemas.

---

## Tools

All tools return either a JSON object (or list) on success, or `{"error": "..."}` on failure. Errors are returned rather than raised so the model receives something readable and actionable instead of a traceback.

### Customer tools

| Tool | Arguments | Behavior |
|---|---|---|
| `create_customer_tool` | `name`, `email`, `phone?` | Creates a customer. Returns `error` if the email already exists. |
| `get_customer_tool` | `customer_id` | Fetches one customer. Returns `error` if not found. |
| `list_customers_tool` | `status?`, `limit?` | Lists customers, optionally filtered by status. |

### Ticket tools

| Tool | Arguments | Behavior |
|---|---|---|
| `create_ticket_tool` | `customer_id`, `subject`, `description`, `priority?` | Creates a ticket. Verifies the customer exists first, so a bad id yields a clear "no customer" error rather than a foreign-key violation. New tickets always start `open`. |
| `list_tickets_tool` | `status?`, `priority?`, `customer_id?`, `limit?` | Lists tickets; filters combine with AND. Invalid filter values return an error listing the valid options. |
| `get_ticket_tool` | `ticket_id` | Fetches one ticket record. |
| `assign_ticket_tool` | `ticket_id`, `team` | Assigns a ticket to a team. Team names are free-form by design. |
| `add_comment_tool` | `ticket_id`, `author`, `body` | Adds a comment to a ticket. |
| `change_ticket_status_tool` | `ticket_id`, `new_status` | Changes status, enforcing the transition graph below. |
| `resolve_ticket_tool` | `ticket_id` | Convenience wrapper that routes through the same validated transition path. |
| `delete_ticket_tool` | `ticket_id`, `confirm` | Permanently deletes a ticket and its comments. Refuses unless `confirm=true`. |

### Context tools

| Tool | Arguments | Behavior |
|---|---|---|
| `get_ticket_details_tool` | `ticket_id` | Returns the aggregated ticket dossier — ticket, customer, and full comment thread — as readable text. |
| `get_knowledge_articles_tool` | `category` | Returns all knowledge-base articles in a category as readable text. |

These two are thin wrappers over the resource functions of the same name. See *Resources vs tools* below for why both exist.

### Ticket status transitions

`change_ticket_status_tool` enforces a state machine rather than allowing arbitrary overwrites:

| From | Allowed to |
|---|---|
| `open` | `in_progress`, `closed` |
| `in_progress` | `resolved`, `open`, `closed` |
| `resolved` | `closed`, `in_progress` (reopened) |
| `closed` | — terminal |

The valid transitions are also written into the tool's description, so the model knows the rules before calling rather than discovering them through failed attempts. Tool descriptions are treated as prompt engineering, not documentation.

---

## Resources

Resources are read-only, URI-addressed context.

**`customer://profile/{customer_id}`** — A customer's profile as formatted text.

**`ticket://details/{ticket_id}`** — The full picture for one ticket: its fields, the customer who raised it, and the entire comment history in order. This traverses the ORM relationships to assemble in one read what would otherwise take several tool calls to stitch together.

**`knowledge://articles/{category}`** — Every knowledge-base article in a category, rendered as a single document. Categories currently seeded: `billing`, `account`.

### Resources vs tools

The distinction that matters is **who initiates the read**:

- **Tools are model-controlled.** The model decides to call them, mid-conversation.
- **Resources are application- or user-controlled.** The host application surfaces them for a person to attach as context. The model cannot autonomously go and fetch one.

This has a direct practical consequence, discovered while testing: a workflow prompt that instructed the model to *"read `ticket://details/3`"* could not be carried out, because the model has no mechanism to fetch a resource on its own.

The fix was to expose the same underlying functions as tools as well (`get_ticket_details_tool`, `get_knowledge_articles_tool`) and point the prompts at those. The resources remain, because they still serve their own purpose — a person can attach a ticket dossier or a policy category directly to a conversation with no tool call involved.

**Rule of thumb: resources are for the human, tools are for the model.** If a workflow needs the model to reach data unprompted, it must be a tool.

---

## Prompts

Prompts are user-invoked, parameterized workflow templates. They are not system prompts, and the model does not trigger them itself — the host surfaces them (typically as a slash command) and the user runs one.

### `triage-ticket(ticket_id)`

A structured triage procedure for a single ticket. It directs the model to:

1. Read the full ticket dossier, including customer and comment history.
2. Check the customer's other tickets for a recurring or escalating pattern.
3. Read the relevant knowledge-base category.
4. Report a summary, a judgment on whether the current priority is right, a recommended owning team, any applicable article, and a next action.

It ends by instructing the model to present its recommendation and wait rather than acting — a workflow-level counterpart to the tool-level `confirm` guard.

### `daily-queue-review()`

A standing, parameterless workflow that reasons across the whole queue rather than drilling into one record. It reviews open and in-progress tickets and surfaces urgent tickets that are unassigned, tickets where the customer commented more recently than the support team, and customers with more than one open ticket.

That last item is deliberate: no single tool answers "which customers have multiple open tickets." Rather than adding a narrow `find_escalations` tool, the prompt describes the analysis and lets the model perform it over `list_tickets_tool` results. This is what prompts unlock that tools alone do not.

---

## Design decisions

**The service layer does not commit.** `log_action()` and every service function call `session.flush()`, never `session.commit()`. The caller's session context manager owns the transaction, so an audit entry and the action it describes succeed or fail together. A failed operation leaves no misleading log entry behind.

**Domain exceptions, not sentinel returns.** Services raise `CustomerNotFoundError`, `DuplicateEmailError`, `TicketNotFoundError`, and `InvalidStatusTransitionError`. The MCP layer catches these specifically and converts them into clean error messages, which keeps SQLAlchemy internals out of the model's view.

**Actor identity via context variables.** The audit log records *who*, not just *what*. Rather than threading an `actor` parameter through every service signature, identity lives in a `contextvars.ContextVar` set once at the entry point. Only `audit_service.py` reads it; no other service function changed. `actor_context()` scopes it correctly with proper reset semantics, which is what per-request identity requires under concurrency.

**Confirmation on destructive actions.** `delete_ticket_tool` refuses to act unless `confirm=true`, and its description states the action is irreversible. Combined with the host's own tool-approval prompt and the prompts' present-then-wait instruction, deletion has three independent checkpoints.

**Filter normalization and explicit validation.** `list_tickets_tool` strips and lowercases its filters (so `""`, `"  "`, and `"Open "` all behave sensibly) and rejects unrecognized values with a message listing the valid ones. Without this, a typo and a genuinely empty result are indistinguishable — the model would report "there are no tickets" when it had simply passed a bad filter. Bad input and an empty result must never look the same.

**Idempotent seeds and migrations.** Both seed scripts skip records that already exist, and `migrate_add_actor.py` checks for the column before altering the table. All three are safe to run repeatedly.

---

## Setup

```bash
uv sync                       # or: pip install -r requirements.txt

# create tables
uv run python -c "from app.database import init_db; init_db()"

# seed data
uv run seed_articles.py
uv run seed_data.py           # add --reset to wipe existing records first
```

### Running

**stdio** (default — for Claude Desktop and other local hosts):

```bash
uv run app/server.py
```

**Streamable HTTP** (for the MCP Inspector or a remote client), on port 3001 at `/mcp`:

```bash
MCP_TRANSPORT=http uv run app/server.py
```

The HTTP entry point builds the ASGI app explicitly and adds CORS middleware exposing the `Mcp-Session-Id` header, which browser-based clients such as the Inspector require for session tracking.

Environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `MCP_TRANSPORT` | Set to `http` for Streamable HTTP; otherwise stdio | stdio |
| `MCP_ACTOR` | Identity recorded in the audit log | `local` |

### Connecting Claude Desktop

Claude Desktop launches the server itself over stdio. In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "customer-support": {
      "command": "uv",
      "args": ["--directory", "/path/to/customer-support-mcp", "run", "app/server.py"],
      "env": { "MCP_ACTOR": "your-name@claude-desktop" }
    }
  }
}
```

Note that Claude Desktop cannot reach the HTTP mode on `localhost`: custom connectors are fetched from Anthropic's infrastructure, so `127.0.0.1` there refers to their host, not yours. Reaching it that way requires a public HTTPS URL (via a tunnel or a deployment).

### Inspecting

```bash
npx -y @modelcontextprotocol/inspector uv run app/server.py    # stdio
npx -y @modelcontextprotocol/inspector                          # then connect to http://127.0.0.1:3001/mcp
```

---

## Limitations and future work

**No test suite.** `tests/` is scaffolded but empty. The service layer was built to be testable — pure functions over an injected session — so the main task is a fixture providing an isolated database per test rather than the live `customer_support.db`.

**SQLite write concurrency.** SQLite serializes writes. This is fine for a single stdio client, but under HTTP with concurrent requests it will produce `database is locked` errors. Everything goes through SQLAlchemy, so migrating to PostgreSQL is largely a connection-string change — though the SQLite-specific `PRAGMA foreign_keys` hook and `check_same_thread` connection argument would become dead code, and `DuplicateEmailError` depends on catching an `IntegrityError` that Postgres raises differently.

**Actor identity is asserted, not authenticated.** `MCP_ACTOR` is configuration, not proof. Over stdio that is defensible — the host launched the process. Over HTTP it is not: identity should come from a verified token per request, which is what `actor_context()` was designed to support but which is not yet wired up.

**Schema changes are manual.** Tables are created with `create_all()`, which cannot alter existing tables — hence the hand-written `migrate_add_actor.py`. Alembic would replace this properly.

**Customer update and delete are not exposed.** `update_customer()` and `delete_customer()` exist and are tested manually in the service layer, but no MCP tool wraps them. Deleting a customer cascades to all their tickets and comments, so exposing it warrants at least the same confirmation guard as ticket deletion.

**Knowledge-base categories are implicit.** `billing` and `account` are conventions established by the seed data, not constrained values. A category with no articles returns an empty-result message rather than an error.
