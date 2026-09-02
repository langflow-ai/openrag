# BomaRAG multi-tenancy and SaaS readiness

This is the architectural reality of the codebase as of the rebrand. Read it
before planning a hosted offering.

## The tenancy model is namespace-per-tenant, not shared-process

BomaRAG is **not** a shared multi-tenant application. A single backend process
serves exactly one tenant, identified by `BOMARAG_TENANT_ID` (default
`bomarag`, see `src/config/settings.py`). That value scopes OpenSearch indices
and is baked into the encryption key derivation (`src/utils/encryption.py`).

Multi-tenancy is achieved at the **infrastructure** layer: the Kubernetes
operator (`kubernetes/operator`) reconciles one `BomaRAG` custom resource per
tenant, each into its own `targetNamespace` with its own `tenantId`, backend,
frontend, Langflow, and OpenSearch. See `BomaRAGSpec.TargetNamespace` and
`BomaRAGSpec.TenantID` in `kubernetes/operator/api/v1alpha1/bomarag_types.go`.

This gives strong isolation (separate data, separate keys, separate blast
radius) at the cost of one full stack per tenant.

## Hard constraint: one worker per backend

`src/app/lifespan.py` raises `RuntimeError("UVICORN_WORKERS>1 is not supported")`
at startup. The reason is that several caches are per-process
`cachetools.TTLCache` instances with no shared backing store:

| Cache | File |
| --- | --- |
| RBAC permission cache | `src/services/rbac_service.py` |
| OAuth subject to DB id | `src/auth/user_identity_cache.py` |
| JWT claims / session | `src/session_manager.py` |
| Langflow ingest token revocation (jti) | `src/services/langflow_ingest_token_service.py` |
| JWKS | `src/utils/jwt_verification.py` |
| Issuer public keys | `src/config/utils.py` |
| Provider health | `src/utils/provider_health_cache.py` |

With more than one process, a role revoke lands in one worker and the others
serve stale permissions for up to `BOMARAG_PERM_CACHE_TTL` seconds. The ingest
token revocation cache is worse: a revoked `jti` is only revoked in the process
that saw the revocation, so a replayed token can still be accepted elsewhere.

**Consequence:** a tenant's backend cannot be horizontally scaled. Capacity per
tenant is capped at one process. Helm `replicaCount` for the backend must stay
at 1.

## What it takes to remove the cap

Ordered by dependency. This is the work to scope before selling a hosted plan
with meaningful per-tenant load.

1. **Shared cache backend.** Introduce a cache interface with `memory` and
   `redis` implementations, gated by the existing `CACHE_BACKEND` env var. Add
   Redis to `docker-compose.yml`, the Helm chart, and the operator's reconcile.
2. **Migrate the security-critical caches first** — RBAC permissions and the
   ingest-token `jti` revocation set. These are correctness bugs under
   multi-process, not just staleness.
3. **Migrate the rest** (identity, session, JWKS, provider health). JWKS and
   provider health are safe to leave per-process; they are read-through caches
   of idempotent data.
4. **Relax the guard** in `src/app/lifespan.py` to allow `UVICORN_WORKERS>1`
   only when `CACHE_BACKEND=redis`.
5. **Raise Helm `replicaCount`** and verify sticky-session assumptions in the
   frontend and Langflow ingest callbacks.

## Interim commercial path

The namespace-per-tenant model is already sellable without any of the above:

- Sell isolated instances ("dedicated tenant"), which is what enterprise buyers
  usually want anyway, and price the isolation as a feature.
- Cap per-tenant concurrency and document it in the SLA.
- Do the Redis work before offering a shared low-cost tier.
