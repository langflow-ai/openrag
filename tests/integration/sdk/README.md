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
| 2 | Send request with invalid API key | Raises `AuthenticationError` with status 401 or 403 |
| 3 | Send request with well-formed but non-existent key | Raises `AuthenticationError` |

---

## Chat (`test_chat.py`)

| # | Test | Expected |
|---|------|----------|
| 4 | Non-streaming chat | Returns non-empty response string |
| 5 | Streaming chat (`create(stream=True)`) | Yields content events with text deltas |
| 6 | Streaming via context manager (`stream()`) | Accumulated `stream.text` is non-empty |
| 7 | `text_stream` async iterator | Yields plain text chunks |
| 8 | `final_text()` | Returns full accumulated response |
| 9 | Conversation continuation (pass `chat_id`) | Second reply uses same conversation |
| 10 | List conversations | Returns list of conversations |
| 11 | Get conversation by ID | Returns conversation with message history |
| 12 | Delete existing conversation | Returns `True` |
| 13 | Chat with ingested document (RAG) | Response sources include the ingested file |
| 14 | Stream continuation with `chat_id` | Follow-up stream uses existing conversation |
| 15 | Every response includes `chat_id` | `chat_id` is a non-empty string |
| 16 | `chat_id` available after stream consumed | `stream.chat_id` is populated |
| 17 | `sources` field on response | Always a list (may be empty) |

---

## Documents (`test_documents.py`)

| # | Test | Expected |
|---|------|----------|
| 18 | Ingest file (async, `wait=False`) | Returns `task_id`; polling reaches terminal state |
| 19 | Ingest file (blocking, `wait=True`) | Returns terminal status with `successful_files >= 0` |
| 20 | Delete ingested document | `success=True`, `deleted_chunks > 0` |
| 21 | Delete never-ingested filename | `success=False`, `deleted_chunks=0`, error message present |
| 22 | Ingest via file object (`io.BytesIO`) | Accepted and processed without error |
| 23 | Re-ingest same filename twice | Does not raise; second call returns a status |
| 24 | Ingest `.md` file | Accepted and processed without error |
| 25 | Poll task status manually | `get_task_status()` returns a status; `wait_for_task()` returns `completed` or `failed` |

---

## Search (`test_search.py`)

| # | Test | Expected |
|---|------|----------|
| 26 | Basic search query | Returns a results list |
| 27 | Search with `limit=1` | Returns at most 1 result |
| 28 | Search with `score_threshold=0.99` | Returns a list (may be empty) without error |
| 29 | Nonsense/obscure query | Returns empty list, no error |
| 30 | Unicode and emoji in query | Returns list, no error |
| 31 | Result fields | Each result has `text` (non-empty string) |

---

## Settings (`test_settings.py`)

| # | Test | Expected |
|---|------|----------|
| 32 | Get settings | Response includes `agent` and `knowledge` sections |
| 33 | Update `chunk_size` setting | Update succeeds; value readable back unchanged |

---

## Models (`test_models.py`)

| # | Test | Expected |
|---|------|----------|
| 34 | List models for a provider (`openai`) | Returns `language_models` and `embedding_models` as lists |

---

## Knowledge Filters (`test_filters.py`)

| # | Test | Expected |
|---|------|----------|
| 35 | Create filter | `success=True`, `id` returned |
| 36 | Search filters by name | Returns list containing the created filter |
| 37 | Get filter by ID | Returns filter with correct `id` and `name` |
| 38 | Update filter description | Update returns `True`; description readable back |
| 39 | Delete filter | Returns `True` |
| 40 | Get deleted filter | Returns `None` |
| 41 | Pass `filter_id` to `chat.create()` | No error; response returned |
| 42 | Pass `filter_id` to `search.query()` | No error; results returned |

---

## Error Handling (`test_errors.py`)

| # | Test | Expected |
|---|------|----------|
| 43 | Connect to dead port | Raises a network exception within timeout |
| 44 | Get conversation with random UUID | Raises `NotFoundError` |
| 45 | Delete conversation with random UUID | Returns `False` |
| 46 | Update settings with invalid value (`chunk_size=-999999`) | Raises `OpenRAGError` subclass |
| 47 | Call `ingest()` with no arguments | Raises `ValueError` |
| 48 | Call `ingest()` with `BytesIO` but no filename | Raises `ValueError` |

---

## End-to-End (`test_e2e.py`)

| # | Test | Expected |
|---|------|----------|
| 49 | Full RAG pipeline: ingest → search → chat | Chat sources include the ingested document |
| 50 | Multi-turn conversation with RAG | Second turn uses same `chat_id`; context carried over |
| 51 | Knowledge filter scopes search and chat | Search and chat succeed with `filter_id`; filter cleaned up |

---

**Total: 51 tests across 8 domains.**
