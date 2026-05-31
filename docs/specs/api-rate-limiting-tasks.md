# Tasks: Rate Limiting for API

> **Cierre (2026-05-31):** Implementación completada con **Valkey 9.x** (BSD-3-Clause) en lugar de Redis (SSPL). Middleware Starlette en `/v1/*`, servicio `RateLimiter`, tests unitarios, y `VALKEY_URL` cableado en `docker-compose.yml`. Ver [`docs/PLAN-DEPLOY.md`](../PLAN-DEPLOY.md) para verificación en deploy.

## Phase 1: Foundation / Configuration

- [x] 1.1 Add RATE_LIMITS config to `config/settings.py` (free: 100, pro: 1000, enterprise: None)
- [x] 1.2 Add VALKEY_URL and RATE_LIMIT_WINDOW to settings
- [x] 1.3 Add Valkey client initialization in `src/main.py` for rate limiting

## Phase 2: Core Implementation

- [x] 2.1 Create `src/services/rate_limiter.py` with RateLimiter class
- [x] 2.2 Implement `check_limit()` method with Valkey + fallback
- [x] 2.3 Implement `increment()` method for counter
- [x] 2.4 Implement `get_tier()` to load tier from OpenSearch or cache

## Phase 3: Integration

- [x] 3.1 Add `get_rate_limiter` dependency in `src/dependencies.py`
- [x] 3.2 Add rate limiting to `/api/v1/search` endpoint
- [x] 3.3 Add rate limiting to `/api/v1/chat` endpoint
- [x] 3.4 Add rate limiting to `/api/v1/documents` endpoint
- [x] 3.5 Add rate limiting to `/api/v1/models` endpoint
- [x] 3.6 Add rate limiting to `/api/v1/knowledge_filters` endpoint

## Phase 4: Testing

- [x] 4.1 Write unit test: RateLimiter.check_limit() returns correct limits for each tier
- [x] 4.2 Write unit test: RateLimiter falls back to in-memory when Valkey unavailable
- [x] 4.3 Write integration test: 429 returned when limit exceeded
- [x] 4.4 Write integration test: X-RateLimit-* headers present in response
- [x] 4.5 Verify all spec scenarios pass

## Phase 5: Cleanup

- [x] 5.1 Add docstrings to RateLimiter class and methods
- [x] 5.2 Verify no debug logs in production code
- [x] 5.3 Update swagger docs with rate limit info
