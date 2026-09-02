---
name: bomarag_dev_stack
description: Start, monitor, restart, or stop the local BomaRAG dev stack (Docker infra + host backend + host frontend). Use when the user says "start the dev stack", "run the app locally", "restart the backend/frontend", "factory-reset", "is the stack up?", or asks to bring services up/down for local development.
---

# BomaRAG local dev stack

The local dev setup has three parts that normally run in three terminals. As an agent, run them from one session: part 1 is a detached Docker command, parts 2 and 3 are long-running processes you must launch **in the background** (however your runtime runs a command without blocking) and monitor.

Run everything from the repo root.

## 1. Infrastructure (OpenSearch, Langflow, Dashboards)

```bash
make dev-local-cpu
```

- Builds langflow/opensearch images if needed, then starts containers detached — the command itself exits when containers are up. Run it in the foreground (first run can take several minutes if images need building; use a generous timeout).
- Endpoints: Langflow http://localhost:7860, OpenSearch http://localhost:9200, Dashboards http://localhost:5601.
- Verify with `docker compose ps` — expect `opensearch`, `dashboards`, and `langflow` containers running/healthy. Wait for OpenSearch to be healthy before starting the backend.

## 2. Backend (host process)

```bash
make backend
```

- Long-running (uvicorn via `uv run python src/main.py`) — launch in the background with its output captured somewhere you can read back. If your runtime already captures background output, don't also tee to a log file.
- Requires `.env` in the repo root (the target errors clearly if missing; fix by copying `.env.example`).
- Serves on http://localhost:8000 (`BOMARAG_BACKEND_PORT`). Ready when uvicorn logs "Application startup complete".

## 3. Frontend (host process)

```bash
make frontend
```

- Long-running (Next.js dev server) — launch in the background with its output captured, same as the backend.
- Installs `frontend/node_modules` automatically on first run.
- Serves on http://localhost:3000 (`FRONTEND_PORT`). Ready when Next prints the local URL / "Ready".

## Restarting

- **Backend only** (the most common case): kill the backend background process, then relaunch `make backend` in the background as in section 2. Same pattern for the frontend.
- **Containers only**: `make stop` then `make dev-local-cpu`.
- **Factory reset** (fix a wedged stack by wiping all state): destructive — removes volumes, `langflow-data/`, `config/`, `data/`, and JWT keys. Get explicit user confirmation before running it. The plain target prompts interactively for "yes", which an agent can't answer, so run:

  ```bash
  make factory-reset FORCE=true
  ```

  Then bring the stack back up: `make dev-local-cpu`, and relaunch backend and frontend.

## Monitoring

- Watch the backend and frontend processes' output for errors; report crashes to the user rather than silently restarting on a loop.
- Container logs: `make logs-os`, `make logs-lf`, or `docker compose logs -f <service>`.
- If the user wants to watch backend/frontend logs themselves, point them at wherever your runtime exposes background process output, or give them a `tail -f` command for the process's log/output file.
- Status check: `docker compose ps` for containers; `curl -s http://localhost:8000/health` for the backend and `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000` for the frontend.

## Stopping

- Backend/frontend: kill their background processes.
- Containers: `make stop` (stops and removes all BomaRAG containers). `make clean` also removes volumes — destructive, only on explicit request.
