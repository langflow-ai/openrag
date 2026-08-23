# OpenRAG Python SDK — QA Test Checklist

Live integration tests against a running OpenRAG instance (`http://localhost:3000` by default).

**Run all SDK tests:**
```bash
make test-sdk
```

---

## Authentication (`test_auth.py`)

| # | Test | Expected |
|---|------|----------|
| 1 | Construct client with no API key | Raises `AuthenticationError` immediately |
| 2 | Construct client with `extra_headers` only (IBM auth mode) and make a real API call | Headers reach the server end-to-end; succeeds, or raises a clean `AuthenticationError` (401) if IBM auth mode isn't enabled on the target instance |
| 3 | Construct client with only `OPENRAG_API_KEY` env var set | Client constructs without error |
| 4 | Explicit `api_key` argument with `OPENRAG_API_KEY` env var also set | Explicit value takes precedence over the env var |
| 5 | Send request with invalid API key | Raises `AuthenticationError` with status 401 or 403 |
| 6 | Send request with well-formed but non-existent key | Raises `AuthenticationError` |

---

## Chat (`test_chat.py`)

| # | Test | Expected |
|---|------|----------|
| 7 | Non-streaming chat | Returns non-empty response string; any `sources` are valid `Source`s with `score` in `[0, 1]` |
| 8 | Chat with `filters`, `limit`, and `score_threshold` together | `len(response.sources) <= limit` |
| 9 | Streaming chat (`create(stream=True)`) | Yields content events with text deltas; the last event is `done` with a non-null `chat_id` |
| 10 | Streaming via context manager (`stream()`) | Accumulated `stream.text` is non-empty |
| 11 | `text_stream` async iterator | Yields plain text chunks |
| 12 | `final_text()` | Returns full accumulated response |
| 13 | Conversation continuation (pass `chat_id`) | Second reply uses same conversation; `followup.chat_id == chat_id` |
| 14 | List conversations | Returns list of conversations; `title`, `created_at`, `last_activity`, `message_count` are correctly typed |
| 15 | Get conversation by ID | Returns conversation with message history; message `role`/`content` are correctly typed |
| 16 | Delete existing conversation | Returns `True` |
| 17 | Chat with ingested document (RAG) | Response sources include the ingested file |
| 18 | Stream continuation with `chat_id` | Follow-up stream uses existing conversation |
| 19 | Every response includes `chat_id` | `chat_id` is a non-empty string |
| 20 | `chat_id` available after stream consumed | `stream.chat_id` is populated |
| 21 | `sources` field on response | Always a list (may be empty) |

---

## Documents (`test_documents.py`)

| # | Test | Expected |
|---|------|----------|
| 22 | Ingest file (async, `wait=False`) | Returns a non-empty `task_id`; polling reaches terminal state |
| 23 | Ingest file (blocking, `wait=True`) | Returns terminal status with `total_files`, `processed_files`, `successful_files`, `failed_files` all populated |
| 24 | Delete ingested document (deterministic ingest) | `success=True`, `deleted_chunks > 0` |
| 25 | Delete never-ingested filename | `success=False`, `deleted_chunks=0`, error message present |
| 26 | `get_task_status()` with a nonexistent task id | Raises `NotFoundError` |
| 27 | Delete by a genuinely nonexistent `filter_id` | Raises `NotFoundError` (distinct from the wildcard-`data_sources` rejection case, which raises a generic `OpenRAGError`) |
| 28 | `wait_for_task()` with a very small `timeout` | Raises `TimeoutError` before the task completes |
| 29 | Ingest via file object (`io.BytesIO`) | Accepted and processed without error |
| 30 | Re-ingest same filename twice | Does not raise; second call returns a status |
| 31 | Ingest `.md` file | Accepted and processed without error |
| 32 | Poll task status manually | `get_task_status()` returns a status; `wait_for_task()` returns `completed` or `failed` |
| 33 | Delete documents by `filter_id` | Removes only the filenames in the filter's `data_sources` |
| 34 | Delete by `filter_id` with wildcard `data_sources` | Rejected with `OpenRAGError` |
| 35 | Delete with both `filename` and `filter_id` | Rejected with `ValueError` |
| 36 | Delete with neither `filename` nor `filter_id` | Rejected with `ValueError` |

---

## Search (`test_search.py`)

| # | Test | Expected |
|---|------|----------|
| 37 | Basic search query | Returns a results list; each result's `score` is in `[0, 1]` |
| 38 | Search with `limit=1` | Returns at most 1 result |
| 39 | Search with `score_threshold=0.99` | Returns a list (may be empty) without error |
| 40 | Search with `score_threshold=0.5` | All returned results have `score >= 0.5` |
| 41 | Nonsense/obscure query | Returns empty list, no error |
| 42 | Unicode and emoji in query | Returns list, no error |
| 43 | Result fields (`limit=5`) | At most 5 results; `text` is a non-empty string; `page`/`mimetype` are `None` or correctly typed |
| 44 | Whitespace-only query (`"   "`) | Raises `ValidationError` |
| 44a | Search with `SearchFilters(data_sources=[filename])` | Wildcard query returns only chunks from that file; a second ingested file is excluded |

---

## Settings (`test_settings.py`)

| # | Test | Expected |
|---|------|----------|
| 45 | Get settings | Response includes `agent` and `knowledge` sections, including `chunk_overlap`, `table_structure`, `ocr`, `picture_descriptions`, and `agent.system_prompt` (each `None` or correctly typed) |
| 46 | Update `chunk_size` setting | Update succeeds; value readable back unchanged |

---

## Models (`test_models.py`)

| # | Test | Expected |
|---|------|----------|
| 47 | List models for a provider (`openai`) | Returns `language_models` and `embedding_models` as lists |
| 48 | List models, parametrized per provider (`openai`, `anthropic`, `ollama`, `watsonx`) | `openai` is required to return typed `ModelOption` entries (`value: str`) with at most one `default`; other providers are marked `SKIPPED` (not failed) if unconfigured (`ValidationError`) |
| 49 | List models for an invalid provider | Raises `ValidationError` |

---

## Knowledge Filters (`test_filters.py`)

| # | Test | Expected |
|---|------|----------|
| 50 | Create filter | `success=True`, `id` returned, `error is None` |
| 51 | Search filters by name | Returns list containing the created filter; a guaranteed-no-match query returns `[]`; `limit=1` returns at most 1 |
| 52 | Get filter by ID | Returns filter with correct `id`, `name`, `query_data`, `owner`, `created_at`, `updated_at` |
| 53 | Update filter description | Update returns `True`; description readable back |
| 54 | Delete filter (wrapped in `try`/`finally` so it can't leak) | Returns `True` |
| 55 | Get deleted filter | Returns `None` |
| 56 | Pass `filter_id` to `chat.create()` | No error; response returned |
| 57 | Pass `filter_id` to `search.query()` | No error; results returned |

---

## Error Handling (`test_errors.py`)

| # | Test | Expected |
|---|------|----------|
| 58 | Connect to dead port | Raises a network exception within timeout |
| 59 | Get conversation with random UUID | Raises `NotFoundError` with `status_code == 404` |
| 60 | Delete conversation with random UUID | Returns `False` |
| 61 | Update settings with invalid value (`chunk_size=-999999`) | Raises `OpenRAGError` subclass |
| 62 | Call `ingest()` with no arguments | Raises `ValueError` |
| 63 | Call `ingest()` with `BytesIO` but no filename | Raises `ValueError` |
| 64 | Iterate a fully-consumed `ChatStream` a second time | Raises `RuntimeError` |
| 65 | `client.close()` with a caller-supplied `http_client` | Does not close the external `httpx.AsyncClient` |
| 66 | API call after an `async with OpenRAGClient(...)` block exits | Raises (the SDK-owned client was closed on `__aexit__`) |

---

## End-to-End (`test_e2e.py`)

| # | Test | Expected |
|---|------|----------|
| 67 | Full RAG pipeline: ingest → search → chat | Chat sources include the ingested document |
| 68 | Multi-turn conversation with RAG | Second turn uses same `chat_id`; context carried over |
| 69 | Knowledge filter scopes search and chat | Search and chat succeed with `filter_id`; filter cleaned up |

---

**Total: 70 tests across 9 domains.**
