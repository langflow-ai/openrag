# Agent Instructions

This repository ships with **agent skills** that any compliant agent can use to help users install OpenRAG and integrate the OpenRAG SDK. The canonical skill files are markdown with YAML frontmatter (the [Agent Skills](https://github.com/anthropics/skills) format), and live under `plugins/openrag/skills/`.

## Available skills

| Skill | File | Purpose |
| --- | --- | --- |
| `openrag_install` | [`plugins/openrag/skills/install/SKILL.md`](plugins/openrag/skills/install/SKILL.md) | Plan and execute a minimal OpenRAG installation, verify locally. |
| `openrag_sdk` | [`plugins/openrag/skills/sdk/SKILL.md`](plugins/openrag/skills/sdk/SKILL.md) | Guide SDK integration (Python, TypeScript, MCP) with code examples. |

## How to use these skills

Pick the path that matches your agent runtime.

### Claude Code (this repo)

`.claude/skills/` symlinks into the plugin, so after cloning the repo the skills are auto-discovered by Claude Code — invoke with `/install` or `/sdk`, or let Claude trigger them automatically based on the description fields.

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
