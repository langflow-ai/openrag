# Agent Instructions

This repository ships with **agent skills** that any compliant agent can use to help users install OpenRAG, integrate the OpenRAG SDK, and run the local dev stack. The canonical skill files are markdown with YAML frontmatter (the [Agent Skills](https://github.com/anthropics/skills) format), and live under `plugins/openrag/skills/`.

## Available skills

| Skill | File | Purpose |
| --- | --- | --- |
| `openrag_install` | [`plugins/openrag/skills/install/SKILL.md`](plugins/openrag/skills/install/SKILL.md) | Plan and execute a minimal OpenRAG installation, verify locally. |
| `openrag_sdk` | [`plugins/openrag/skills/sdk/SKILL.md`](plugins/openrag/skills/sdk/SKILL.md) | Guide SDK integration (Python, TypeScript, MCP) with code examples. |
| `openrag_dev_stack` | [`plugins/openrag/skills/dev-stack/SKILL.md`](plugins/openrag/skills/dev-stack/SKILL.md) | Start, monitor, restart, or stop the local dev stack (Docker infra + host backend + host frontend). |

## How to use these skills

Pick the path that matches your agent runtime.

### Claude Code (this repo)

`.claude/skills/` symlinks into the plugin, so after cloning the repo the skills are auto-discovered by Claude Code — invoke with `/install`, `/sdk`, or `/dev-stack`, or let Claude trigger them automatically based on the description fields.

### Claude Code (install globally, any repo)

```
/plugin marketplace add langflow-ai/openrag
/plugin install openrag@openrag
```

### Claude Agent SDK / other skill-aware runtimes

Point your skill loader at `plugins/openrag/skills/`. Each subdirectory is one skill.

### Any other agent (generic)

Read the `SKILL.md` files directly. The frontmatter `description` tells you when the skill is relevant; the body is the instruction set to follow.

## Skill authoring notes

- Skill bodies are intentionally kept agent-neutral. Do not add references to tools or features that only exist in one runtime (for example, do not name specific slash commands, hook systems, or task-tracking tools).
- Claude-Code-specific plumbing belongs in `plugin.json` or `.claude/`, not in `SKILL.md`.
- See `plugins/README.md` for the full layout and distribution model.

## Frontend tests

Two suites live in `frontend/`, and **the file extension names the runner**:

| Pattern | Runner | Command | Needs a backend? |
|---|---|---|---|
| `**/*.test.ts(x)` | Vitest | `npm test` (`test:watch`) | No |
| `tests/**/*.spec.ts` | Playwright | `npx playwright test` | Yes — full Docker stack |

- **Co-locate** Vitest files with their source: `lib/metrics.ts` → `lib/metrics.test.ts`, `components/task-dialog/filters.tsx` → `components/task-dialog/filters.test.tsx`.
- `tests/` is Playwright's `testDir` and holds only `.spec.ts`. Shared Vitest infrastructure lives in `test-utils/`, never in `tests/`.
- Query by accessible role/label/text. Do not assert on class names or add test-only ids — tests should fail on user-visible behaviour changes, not markup refactors.
- Never `vi.mock` a module in `app/api/queries/` or `app/api/mutations/`. Mock the network instead, so the URL, `response.ok` handling, payload shape, and react-query wiring stay under test.
- Use `renderWithProviders` from `test-utils/render.tsx`, not `app/providers.tsx`. The latter monkey-patches `window.fetch` for 401 redirects, and `app/api/get-query-client.ts` memoizes one client per browser process, which leaks cache between tests.

**Diff coverage gate.** PRs must cover the lines they change: `npm run test:diff-coverage` runs the suite and then `scripts/check-diff-coverage.mjs`, which fails when under 80% of *changed executable lines* are covered. Enforced by the `diff-coverage` job in `test-frontend-unit.yml`.

The gate is on changed **lines**, not changed files — a one-line fix to an untested legacy file is not blocked, but new logic must come with tests. It diffs the merge base against the working tree, so it also reports on uncommitted work locally. Tune with `--threshold` / `--base` or `DIFF_COVERAGE_THRESHOLD` / `DIFF_COVERAGE_BASE`.

There is deliberately **no global coverage threshold** (overall is ~5%). A global floor rewards writing the cheapest tests; the diff gate makes new code carry its own weight, and existing gaps get closed by churn priority instead — target the files git history shows are repeatedly fixed, not the ones that look most complex.

**What does not belong in Vitest.** jsdom has no CSS engine and no layout: `getBoundingClientRect()` returns zeros, and `pointer-events`, `opacity`, and other style-driven guards are never applied. Anything whose behaviour depends on real geometry or real CSS — ag-grid virtualization, `use-stick-to-bottom`, `disabled:pointer-events-none` on a Radix trigger — belongs in Playwright. A component's *disabled attribute* is testable in Vitest; the *click being blocked by CSS* is not.

Design notes and phased rollout: `local/plans/frontend-testing-foundation.md`.

## Operational constraints

**Single-worker only (until Redis cache lands).** The RBAC permission cache and OAuth-subject→DB-id cache are both per-process (`cachetools.TTLCache`). Running with multiple uvicorn workers or multiple helm replicas means a role grant or revoke takes effect in only one process; the others serve stale permissions for up to `OPENRAG_PERM_CACHE_TTL` seconds (default 60). The startup event in `src/main.py` enforces `UVICORN_WORKERS<=1` and `CACHE_BACKEND=memory` and hard-fails otherwise. To horizontally scale, swap the cache to Redis first.

**RBAC is opt-in.** `OPENRAG_RBAC_ENFORCE` defaults to `false`, which makes OpenRAG behave like the pre-RBAC release: every authenticated user has full access; API-key role overrides are also bypassed. To turn the permissions system on (admin/developer/user/viewer roles, `require_permission` gates, audit denials), set `OPENRAG_RBAC_ENFORCE=true`. Available in all `OPENRAG_RUN_MODE` values — operators own the trade-off. The startup event logs the enforcement state on every boot.

**Dev-local with backend on host.** When you run `make dev-local-cpu` (or `dev-local`) and then `make backend` on the host, OpenSearch needs to resolve `openrag-backend` to the host machine so it can fetch JWKS for OIDC validation. Langflow also needs that name for backend ingest callbacks. The base `docker-compose.yml` does NOT add this alias — it would break CI, where the backend is a docker-compose service. To enable the host-backend mode, layer the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.host-backend.yml up -d opensearch dashboards langflow
make backend     # in another terminal
make frontend    # in another terminal
```

The override only adds `extra_hosts: openrag-backend:host-gateway` to the OpenSearch and Langflow services. Without it, OIDC and ingest callbacks work because docker DNS routes `openrag-backend` to the in-compose backend container.
