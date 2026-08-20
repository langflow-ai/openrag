# LiteLLM MVP — Spec

Scoped-down version of the `litellm-openai-compatible-router` spike branch.
Ship LiteLLM as the internal routing layer with an OpenAI-compatible `/v1` proxy
for Langflow, without exposing the full provider catalogue or redesigning the
frontend settings/onboarding UX.

## Goals

- Replace direct provider API calls with LiteLLM routing behind the scenes.
- Expose `/v1/chat/completions`, `/v1/embeddings`, `/v1/models` as an internal
  OpenAI-compatible proxy so Langflow never holds upstream vendor keys.
- Use the static LiteLLM model catalog (no live provider API fetches) to drive
  the model picker with capability badges and pricing info.
- Filter everything to the 4 currently supported providers: OpenAI, Anthropic,
  WatsonX, Ollama.

## Non-goals (deferred)

- Exposing the full ~100 LiteLLM provider catalogue in the UI.
- Generic provider settings dialog or generic onboarding credential forms.
- External user access to `/v1` endpoints (internal Langflow hop only).
- Token refresh mechanism for the hop JWT.
- Consolidating the 4 existing provider validation paths through LiteLLM.
- Provider logo directory / catalogue card grid on settings page.

---

## Scope — what to bring from the spike

### Backend — new files

| File | Purpose |
|------|---------|
| `src/services/llm_gateway.py` | LiteLLM-backed gateway (`acompletion` / `aembedding`) |
| `src/services/model_catalog.py` | Static catalog from LiteLLM data, filtered to 4 providers |
| `src/services/langflow_llm_token_service.py` | Short-lived hop JWT issuance |
| `src/api/v1/llm.py` | `/v1/chat/completions`, `/v1/embeddings` endpoints |
| `src/dependencies.py` | New dependency injection wiring |
| `src/api/models.py` | Model-related endpoint additions |

### Backend — modified files

| File | Change |
|------|--------|
| `src/config/config_manager.py` | `GenericProviderConfig`, `custom` dict, `set_credentials()`, `credential_values()` |
| `src/config/settings.py` | `get_langflow_llm_base_url()`, `get_langflow_llm_proxy_ttl_seconds()` |
| `src/api/v1/models.py` | Catalog-driven `/v1/models` |
| `src/api/settings/endpoints.py` | Settings wiring for credentials |
| `src/api/settings/models.py` | Response model additions |
| `src/api/settings/helpers.py` | Settings helper updates |
| `src/api/settings/langflow_sync.py` | Hop token + base URL sync (replaces per-provider secret push) |
| `src/api/provider_validation.py` | `_test_litellm_provider()` for future providers; existing 4 keep their validation paths |
| `src/api/provider_health.py` | `credential_values()` integration |
| `src/services/flows_service.py` | Proxy field mappings (`OPENRAG_LLM_TOKEN`, `OPENRAG_LLM_BASE_URL`) |
| `src/services/models_service.py` | LiteLLM routing |
| `src/services/chat_service.py` | LiteLLM routing |
| `src/auth/request_identity.py` | Hop token auth support |
| `src/utils/langflow_headers.py` | Header injection for hop token |
| `src/utils/provider_health_cache.py` | Cache updates |
| `src/app/container.py` | Service registration |
| `src/app/routes/internal.py` | Route registration |
| `src/app/routes/public_v1.py` | Route registration |
| `src/mcp_http/server.py` | MCP integration |

### Langflow components + flows

| File | Purpose |
|------|---------|
| `custom_components/openrag/__init__.py` | Package init |
| `custom_components/openrag/openai_compatible_llm.py` | LLM component pointing at OpenRAG `/v1` |
| `custom_components/openrag/openai_compatible_embedding.py` | Embedding component pointing at OpenRAG `/v1` |
| `flows/components/openai_compatible_llm.py` | Same (flows copy) |
| `flows/components/openai_compatible_embedding.py` | Same (flows copy) |
| `flows/component_index.json` | Component registration |
| `flows/ingestion_flow.json` | Updated to use new components |
| `flows/openrag_agent.json` | Updated to use new components |
| `flows/openrag_nudges.json` | Updated to use new components |
| `flows/openrag_url_mcp.json` | Updated to use new components |

### Frontend — bring

| File | Purpose |
|------|---------|
| `app/onboarding/_components/model-selector.tsx` | Catalog-driven picker changes |
| `app/onboarding/_components/model-features.tsx` | Capability badge strip (new) |
| `app/settings/_helpers/catalog-models.ts` | Catalog data layer (new) |
| `app/settings/_helpers/catalog-models.test.ts` | Tests for above (new) |
| `app/settings/_helpers/model-info.ts` | Capability/pricing formatters (new) |
| `app/api/queries/useGetModelsQuery.ts` | Models API query hook (new) |
| `app/api/queries/useGetSettingsQuery.ts` | Minor additions |
| `app/api/mutations/useOnboardingMutation.ts` | Minor additions |
| `app/api/mutations/useUpdateSettingsMutation.ts` | Minor additions |

### Infrastructure

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Env var wiring for `/v1` hop |
| `Dockerfile.langflow` | Component installation |
| `Dockerfile.langflow.dev` | Dev component installation |
| `.env.example` | New env var documentation |

### Tests — bring (new)

| File | Covers |
|------|--------|
| `tests/unit/api/test_v1_llm.py` | `/v1` endpoint tests |
| `tests/unit/config/test_generic_provider_config.py` | Config layer tests |
| `tests/unit/dependencies/test_jwt_header_auth.py` | Hop token auth |
| `tests/unit/services/test_llm_gateway.py` | Gateway routing |
| `tests/unit/services/test_model_catalog.py` | Catalog tests |
| `tests/unit/services/test_langflow_llm_token_service.py` | Token service |
| `tests/unit/services/test_flows_service_bulk_update.py` | Flow update tests |
| `tests/unit/test_langflow_llm_proxy_headers.py` | Header injection |
| `tests/unit/test_models_api_errors.py` | Error handling |
| `tests/unit/test_openai_compatible_langflow_components.py` | Component tests |
| `tests/unit/test_patch_langflow_openrag_bundle.py` | Bundle patching |
| `tests/unit/test_provider_health_cache_key.py` | Health check cache |

### Tests — bring (modified)

| File | Change |
|------|--------|
| `tests/unit/api/test_settings_endpoints.py` | `credential_values` additions |
| `tests/unit/test_langflow_global_variables.py` | Hop token sync |
| `tests/unit/test_langflow_ingest_callback.py` | Minor |
| `tests/unit/test_flow_opensearch_outputs.py` | Minor |
| `tests/integration/core/test_mcp_url_ingest.py` | Minor |

---

## Scope — what NOT to bring from the spike

### Frontend — do not bring

| File | Reason |
|------|--------|
| `app/settings/_components/generic-provider-dialog.tsx` | Generic provider UI — deferred |
| `app/settings/_components/catalog-provider-card.tsx` | Catalogue card grid — deferred |
| `app/onboarding/_components/onboarding-credential-fields.tsx` | Generic credential form — deferred |
| `app/onboarding/_components/onboarding-card.tsx` rewrite | Keep main's version with bespoke provider tabs |
| `frontend/public/provider-logos/*` | Only needed for full catalogue UI |
| `app/settings/_helpers/provider-logos.ts` + test | Only needed for full catalogue UI |
| `app/settings/_components/model-providers.tsx` changes | Settings page stays as-is |

### Frontend — do not delete

| File | Reason |
|------|--------|
| `app/api/queries/useComponentActions.ts` | Used by console status panel |
| `app/api/queries/useComponentLogsQuery.ts` | Used by console status panel |
| `app/api/queries/useConsoleStatusQuery.ts` | Used by console status panel |
| `app/api/[...path]/route.ts` | Catch-all route, may be in use |
| `app/onboarding/_components/anthropic-onboarding.tsx` | Keep bespoke forms |
| `app/onboarding/_components/openai-onboarding.tsx` | Keep bespoke forms |
| `app/onboarding/_components/ibm-onboarding.tsx` | Keep bespoke forms |
| `app/onboarding/_components/ollama-onboarding.tsx` | Keep bespoke forms |
| `app/onboarding/_components/advanced.tsx` | Keep bespoke forms |
| `app/onboarding/_components/tab-trigger.tsx` | Keep bespoke forms |
| `app/onboarding/_hooks/useModelSelection.ts` | Keep bespoke forms |

### Backend — do not bring (unrelated changes)

| File | Reason |
|------|--------|
| `src/services/search_service.py` | Facet aggregation simplification — unrelated |
| `src/services/file_service_v2.py` | Filter type changes — unrelated |
| `src/api/files.py` | Filter type changes — unrelated |
| `src/utils/logging_config.py` | Component buffer removal — unrelated |

### Backend — do not delete

| File | Reason |
|------|--------|
| `src/services/component_logs.py` | Used by logging/console — unrelated cleanup |
| `src/services/status_checks.py` | Used by status panel — unrelated cleanup |
| `src/services/status_diagnostics.py` | Used by status panel — unrelated cleanup |
| `src/services/status_service.py` | Used by status panel — unrelated cleanup |
| `src/api/schemas/status.py` | Used by status routes — unrelated cleanup |
| `src/api/v1/status.py` | Used by status routes — unrelated cleanup |

### Tests — do not delete

| File | Reason |
|------|--------|
| `tests/unit/api/test_status_logs_endpoint.py` | Tests for kept status code |
| `tests/unit/api/test_status_route_gating.py` | Tests for kept status code |
| `tests/unit/services/test_component_logs.py` | Tests for kept component_logs |
| `tests/unit/services/test_status_checks.py` | Tests for kept status_checks |
| `tests/unit/services/test_status_service.py` | Tests for kept status_service |
| `tests/unit/test_query_acl_filtering.py` | Tests for kept search code |

---

## Key design decisions

1. **LiteLLM is internal only.** Users never interact with LiteLLM directly.
   The 4 supported providers are the only ones exposed in the UI.
2. **Static catalog, no live fetches.** Model lists come from LiteLLM's bundled
   `model_cost` data. Users can type custom model names manually.
3. **Existing validation paths preserved.** The 4 providers keep their
   battle-tested validation. `_test_litellm_provider()` is for future providers.
4. **Config layer has generic support ready.** `GenericProviderConfig` /
   `credential_values()` / `set_credentials()` ship now — they're already
   load-bearing for the gateway and health checks.
5. **Hop token, no refresh.** Langflow gets a short-lived JWT. TTL defaults to
   the ingest callback TTL. No refresh mechanism yet — token just needs to be
   long enough for the operation.
6. **`/v1` is internal-only.** Authenticated via hop token. No external user
   access until auth, rate-limiting, and billing are designed.

## Source branch

All changes originate from `litellm-openai-compatible-router`. The MVP branch
was cut from that spike (not from main) and scoped down by reverting/removing
out-of-scope changes.

## Implementation status (2026-08-20)

**Branch `mvp-litellm` exists and scoping is complete. Nothing is committed yet.**

### Done

- Branch created off `litellm-openai-compatible-router`
- Diff trimmed from 183 files to 90 files (12,209 insertions / 6,250 deletions)
- Restored 28 files the spike deleted that are still in use on main (status
  panel, console queries, per-provider onboarding components, search/file
  services, logging, and their tests)
- Removed 6 out-of-scope frontend additions: `generic-provider-dialog.tsx`,
  `catalog-provider-card.tsx`, `onboarding-credential-fields.tsx`,
  `provider-logos.ts`, `provider-logos.test.ts`, `public/provider-logos/` dir
- Reverted `model-providers.tsx`, `model-helpers.tsx`, `onboarding-card.tsx`,
  `health.py` to main's versions
- Reverted `internal.py` and `public_v1.py` to main, then surgically re-added
  only the `/models/catalog` and `/v1` LLM proxy route registrations
- Fixed `model-features.tsx`: replaced `provider-logos` imports with built-in
  logo components (`OpenAILogo`, `AnthropicLogo`, `IBMLogo`, `OllamaLogo`)
- Widened `getModelLogo` signature from `ModelProvider` to `string` to match
  catalog-driven callers in agent/ingest settings sections
- Filtered the public model catalog to the four supported providers only:
  OpenAI, Anthropic, WatsonX, and Ollama
- Restored the remaining console/status UI and metrics files plus their
  integration points from `main`; the earlier status incorrectly said this
  restoration was already complete

### Validated

- 186 backend tests pass (74 new + 80 restored + 32 modified):
  `pytest tests/unit/services/test_llm_gateway.py tests/unit/services/test_model_catalog.py tests/unit/config/test_generic_provider_config.py tests/unit/api/test_v1_llm.py tests/unit/services/test_langflow_llm_token_service.py tests/unit/test_langflow_llm_proxy_headers.py tests/unit/test_openai_compatible_langflow_components.py tests/unit/test_patch_langflow_openrag_bundle.py tests/unit/test_provider_health_cache_key.py tests/unit/test_models_api_errors.py tests/unit/services/test_flows_service_bulk_update.py tests/unit/services/test_component_logs.py tests/unit/services/test_status_checks.py tests/unit/services/test_status_service.py tests/unit/api/test_status_logs_endpoint.py tests/unit/api/test_status_route_gating.py tests/unit/test_query_acl_filtering.py tests/unit/api/test_settings_endpoints.py tests/unit/test_langflow_global_variables.py tests/unit/test_langflow_ingest_callback.py tests/unit/test_flow_opensearch_outputs.py`
- TypeScript `tsc --noEmit` clean (only pre-existing `metrics.ts` error from main)
- Re-ran the same 186-test backend suite after the catalog filter and console
  restoration: all 186 pass
- TypeScript `tsc --noEmit` is fully clean after restoring `prom-client` from
  `main`'s package manifest and refreshing local dependencies
- Functional smoke check: backend `/health` returns `{"status":"ok"}` and the
  frontend root plus `/settings/providers` return HTTP 200

### Not yet done

- Nothing committed — the scoping work remains a mix of staged and unstaged
  changes on `mvp-litellm`
- Authenticated provider selection and live LLM calls have not been exercised
  end-to-end; they require an authenticated browser session and configured
  provider credentials
- The existing OpenSearch container is operational (`yellow`) but Docker marks
  it unhealthy because `main`'s healthcheck reads an unset in-container
  `OPENSEARCH_PASSWORD`; this is pre-existing and outside the LiteLLM diff
- `src/dependencies.py` and `src/api/models.py` are listed under "new files" in
  the scope tables above but are actually pre-existing files with additions —
  treat as modified, not new, when cherry-picking
