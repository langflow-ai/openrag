# OpenRAG Python SDK smoke tests (remote / IBM SaaS)

A standalone [uv](https://docs.astral.sh/uv/) project that exercises **every
functionality of the [`openrag-sdk`](https://pypi.org/project/openrag-sdk/)
Python client** against a remote OpenRAG deployment and writes a pass/fail
report. Designed for IBM SaaS deployments, where authentication uses a
username + API key (sent as `X-Username` / `X-Api-Key` headers) instead of the
self-hosted `OPENRAG_API_KEY` flow.

The checks mirror the repo's pytest integration suite
(`tests/integration/sdk/`) but run standalone — no pytest, no local backend,
no onboarding step.

## Setup

```bash
cd scripts/test_scripts/sdk/python
uv sync                 # installs the latest openrag-sdk from PyPI
cp .env.example .env    # then fill in your URL, username, and API key
```

To pick up a newer SDK release later: `uv lock --upgrade && uv sync`.

The project depends on the latest `openrag-sdk` published to PyPI (currently
0.3.1). The two delete-by-filter_id checks need the unreleased 0.4.0 API and
auto-skip (with a reason in the report) until that version ships — re-run
`uv lock --upgrade` once it does.

## Run

```bash
uv run python main.py                          # full run, config from .env
uv run python main.py --only search,chat       # subset of suites
uv run python main.py \
  --url https://your-instance.example.com \
  --username you@example.com \
  --api-key YOUR_KEY                           # explicit credentials
```

Configuration precedence: CLI flags > environment variables > `.env`.

| Setting | CLI flag | Env var |
|---|---|---|
| Base URL | `--url` | `OPENRAG_URL` |
| Username | `--username` | `OPENRAG_USERNAME` |
| API key | `--api-key` | `OPENRAG_API_KEY` |
| Request timeout (default 120s) | `--timeout` | — |
| Suites to run | `--only` | — |
| Report directory | `--report-dir` | — |

## What it checks

Suites run in end-to-end order (documents are ingested before search/chat so
retrieval has content to find):

| Suite | Checks |
|---|---|
| `settings` | get; update round-trip (re-sets the current chunk_size — never changes configuration) |
| `models` | list models for openai / anthropic / ollama / watsonx (unavailable providers are skipped) |
| `documents` | ingest with wait; ingest no-wait + task polling; ingest from a file object; re-ingest same filename; delete by filename; idempotent delete of a missing file; delete by filter_id |
| `search` | basic query (with retries for index latency); limit; score_threshold; nonsense query; unicode query |
| `chat` | non-streaming; streaming via `create(stream=True)`; `stream()` context manager; multi-turn with chat_id; list / get / delete conversations |
| `filters` | full CRUD; filter_id actually scopes search and chat results |
| `errors` | NotFoundError on missing conversation; invalid settings rejected; client-side ValueErrors; bogus filter_id rejected |

A preflight `GET /api/v1/settings` runs first. It is **non-fatal**: an HTTP
error (e.g. `permission_denied`) is logged, recorded in the report as
`preflight.settings_get`, and the run continues so every endpoint gets its own
verdict. Only an unreachable host aborts the run (exit 2).

Checks that depend on earlier ones (e.g. search needs an ingested document)
are auto-skipped — not failed — when their prerequisite didn't pass.

All artifacts the run creates (documents, conversations, knowledge filters)
are deleted in a best-effort cleanup phase at the end, even on Ctrl-C.

> Note: the integration suite's wildcard delete-by-filter test
> (`data_sources: ["*"]` must be rejected) is intentionally omitted — if the
> backend ever failed to reject it, it would delete every document in the
> tenant. Not worth the risk against a live SaaS instance.

## Report

Each run prints live results to the console and writes:

- `reports/report.json` / `reports/report.md` — latest run
- `reports/report_<UTC timestamp>.json` / `.md` — per-run history
- `reports/run_<UTC timestamp>.log` — full console log of the run

Reports include the timestamp, target URL, masked credentials, SDK version,
and per-check status / duration / error. Exit code: `0` all passed (skips
allowed), `1` at least one failure, `2` bad configuration or unreachable
instance.
