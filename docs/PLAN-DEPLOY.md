# Plan de deploy — Axioma 2.0 (OpenRAG)

> Guía operativa para desplegar el MVP (chat RAG + ingesta + API v1) en **local (Windows/WSL2)** y **VPS Linux**, con **Ollama** + **Docker Compose**.
>
> Última actualización: 2026-05-31

---

## Objetivo

Instancia **funcional y reproducible** corrigiendo gaps entre documentación y código (Valkey cableado, `.env`, smoke tests).

**Fuera de alcance MVP:** Kubernetes, SGLang, SSO/SAML, billing, Fase 3–4 enterprise ([PLAN-ESTRATEGICO.md](./PLAN-ESTRATEGICO.md)).

---

## Diagnóstico (estado vs código)

| Área | Estado | Acción |
|------|--------|--------|
| Core RAG + Langflow + OpenSearch | OK | Deploy + smoke tests |
| API v1, MCP, OAuth, conectores | OK | Validar tras deploy |
| Rate limit + semantic cache | Código OK; Valkey en Compose | `VALKEY_URL=redis://valkey:6379/0` en backend |
| LLMRouter Granite | Módulo existe; **no usado en chat** | Granite vía **Langflow** (componente Ollama) |
| Guardian, HybridChunker, Ragas | Código OK; flags OFF por defecto | Fase 4 — activación opt-in |
| `.env` | No versionado | Copiar desde `.env.example` |

**Rutas API:** el backend expone `/v1/*`; el frontend Next.js proxy expone `/api/v1/*` hacia el backend.

---

## Fase 1 — Infra y documentación (repo)

### Valkey en Docker Compose

El servicio `openrag-backend` debe recibir:

```yaml
VALKEY_URL=${VALKEY_URL:-redis://valkey:6379/0}
depends_on:
  valkey:
    condition: service_healthy
```

Sin esto, el default `redis://localhost:6379/0` apunta al loopback del contenedor y el rate limit cae a memoria.

### Validación

```bash
docker compose config
```

---

## Fase 2 — Deploy local (Windows + WSL2)

### Prerrequisitos

| Herramienta | Uso |
|-------------|-----|
| Docker Desktop (backend WSL2) | Stack Compose (6 servicios) |
| Python 3.13 + `uv` en WSL | Docling en puerto 5001 |
| Ollama en WSL (`11434`) | LLM + embeddings |
| RAM Docker ≥ 8 GB, disco ≥ 50 GB | OpenSearch + Langflow |

### 1. Crear `.env`

```bash
cp .env.example .env
```

Editar valores sensibles (no commitear `.env`; está en `.gitignore`):

```env
OPENSEARCH_PASSWORD=<fuerte>
LANGFLOW_SUPERUSER=admin
LANGFLOW_SUPERUSER_PASSWORD=<fuerte>
LANGFLOW_SECRET_KEY=<generado>
LANGFLOW_AUTO_LOGIN=False
OLLAMA_ENDPOINT=http://host.docker.internal:11434
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=<modelo-embeddings>
LLM_PROVIDER=ollama
LLM_MODEL=<modelo-chat>
VALKEY_URL=redis://valkey:6379/0
OPENRAG_ENCRYPTION_KEY=<opcional local; obligatorio VPS>
```

### 2. Modelos Ollama

```bash
ollama pull granite4.0-htiny:instruct    # chat en Langflow
ollama pull <embedding-model>            # misma dimensión para todo el índice
```

### 3. Docling (obligatorio, puerto 5001)

En WSL, desde la raíz del repo:

```bash
uv sync
uv run python scripts/docling_ctl.py start --port 5001
uv run python scripts/docling_ctl.py status
```

### 4. Levantar stack

```bash
make ensure-langflow-data ensure-backend-volumes
make dev-cpu
docker compose ps   # opensearch, dashboards, backend, frontend, langflow, valkey
```

### 5. Smoke tests manuales

| # | Prueba | Éxito |
|---|--------|-------|
| 1 | http://localhost:3000 carga | UI OK |
| 2 | Onboarding → Ollama | Settings guardados |
| 3 | Subir PDF pequeño | Task complete |
| 4 | Chat con pregunta sobre el PDF | Respuesta con contexto |
| 5 | `curl -s http://localhost:3000/api/health` | 200 |
| 6 | Crear API key → `POST /api/v1/search` con Bearer | 200 + headers `X-RateLimit-*` |

### 6. Tests automatizados (opcional)

```bash
make test-os-jwt
# OPENRAG_URL=http://localhost:3000 make test-sdk
```

### Bloqueadores en Windows (sin WSL/Docker activo)

Si solo se dispone del host Windows sin Docker/Ollama/Docling en ejecución:

| Paso | Estado típico en Windows puro |
|------|-------------------------------|
| `docker compose config` | OK si Docker Desktop instalado |
| `make dev-cpu` | Requiere Docker + `.env` |
| Docling `:5001` | Requiere WSL + `uv` |
| Ollama | Requiere Ollama en WSL o host |
| Smoke E2E | Manual tras stack completo |

**Criterio de salida Fase 2:** MVP local estable; logs backend sin errores recurrentes OpenSearch/Langflow.

---

## Fase 3 — Deploy VPS (producción ligera)

### Infra recomendada

- Ubuntu 22.04/24.04
- Mínimo **8 GB RAM** (16 GB si Ollama + OpenSearch en el mismo host)
- Docker + Compose; `uv`; Ollama; Docling como **systemd**

### Hardening

| Item | Acción |
|------|--------|
| Secrets | `OPENRAG_ENCRYPTION_KEY`, `SESSION_SECRET`, passwords únicos |
| `OPENRAG_ENFORCE_PREREQUISITES=true` | Falla arranque si falta encryption key |
| Red | Solo **80/443** públicos; cerrar 9200, 6379, 7860 (7860 solo admin VPN) |
| TLS | Caddy/Nginx → `127.0.0.1:3000` |
| Timeouts proxy | ≥ 300s (ingesta larga; alinear con `LANGFLOW_TIMEOUT`) |
| OAuth | Redirect `https://<dominio>/auth/callback`; `WEBHOOK_BASE_URL` si conectores |
| Backups | Volúmenes `opensearch-data`, `langflow-data`, `redis-data`, `./keys`, `./config` |
| Langflow DB | Valorar `LANGFLOW_DATABASE_URL=postgresql://...` |

### systemd — Docling (ejemplo)

```ini
# /etc/systemd/system/axioma-docling.service
[Unit]
Description=Axioma Docling Serve
After=network.target

[Service]
Type=simple
User=axioma
WorkingDirectory=/opt/Axioma-2.0-1
ExecStart=/home/axioma/.local/bin/uv run python scripts/docling_ctl.py start --port 5001 --foreground
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### systemd — Stack Compose (ejemplo)

```ini
# /etc/systemd/system/axioma-compose.service
[Unit]
Description=Axioma Docker Compose
Requires=docker.service
After=docker.service axioma-docling.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/Axioma-2.0-1
EnvironmentFile=/opt/Axioma-2.0-1/.env
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

### TLS con Caddy (ejemplo)

```caddyfile
axioma.example.com {
    reverse_proxy 127.0.0.1:3000 {
        transport http {
            read_timeout 300s
            write_timeout 300s
        }
    }
}
```

### Firewall (ufw)

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
# NO abrir 9200, 6379, 7860 al público
```

### Despliegue

```bash
git clone <repo> && cd Axioma-2.0-1
cp .env.example .env   # editar producción
make dev-cpu
```

### Verificación post-deploy (Fase 3)

- Repetir smoke tests Fase 2 vía HTTPS
- `docker compose logs` sin OOM OpenSearch
- Rate limit: HTTP 429 tras exceder tier con la misma API key

**Criterio de salida Fase 3:** URL pública con TLS; checklist Fase 2 en verde.

---

## Fase 4 — Extensiones Axioma (opt-in)

Activar tras VPS estable. Cambiar modelo de embedding implica **re-ingerir** documentos.

### Granite en chat (Langflow, no LLMRouter)

El chat RAG usa **flows Langflow**, no `src/services/llm_router.py`.

1. Abrir Langflow UI (`http://localhost:7860` o vía VPN en prod).
2. Editar el flow de chat (`LANGFLOW_CHAT_FLOW_ID`).
3. En el componente **Ollama** del agente, model: `granite4.0-htiny:instruct`.
4. Asegurar `OLLAMA_ENDPOINT` / `OLLAMA_BASE_URL` apunta al host Ollama.
5. Probar query multi-hop en la UI de Axioma.

### Guardian (guardrail async)

```env
GUARDIAN_ENABLED=true
GUARDIAN_SAMPLE_RATE=0.1
GUARDIAN_MODEL=granite-guardian-3.3:8b
```

```bash
ollama pull granite-guardian-3.3:8b   # VPS pequeño: modelo 2B si aplica
```

Verificar scores `guardian/*` en Langfuse.

### HybridChunker + context expansion

```env
HYBRID_CHUNKER_ENABLED=true
CONTEXT_EXPANSION_ENABLED=true
```

Solo afecta **documentos ingeridos después** del cambio. Verificar campos `section_title`, `chunk_index` en OpenSearch.

### Langfuse

```env
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

Trazas visibles en dashboard Langfuse (Langflow ya recibe las vars en Compose).

### Ragas batch (cron)

Requiere Langfuse + juez (script usa OpenAI por defecto):

```bash
# crontab -e
0 2 * * * cd /opt/Axioma-2.0-1 && uv run python scripts/ragas_batch_eval.py >> /var/log/axioma-ragas.log 2>&1
```

**Criterio de salida Fase 4:** checklist PLAN-ESTRATEGICO Fase 2 cumplido en staging/producción.

---

## Fase 5 — Post-MVP (backlog)

- OpenSearch Dashboards: DLS/FLS, ISM, alertas
- SSO/SAML, audit logs
- White-label frontend
- SGLang (`GRANITE_BACKEND=sglang`)
- Multi-agent + MCP externo
- Billing / rate plans UI

---

## Archivos clave

| Rol | Ruta |
|-----|------|
| Compose | `docker-compose.yml` |
| Env plantilla | `.env.example` |
| Settings | `src/config/settings.py` |
| Rate limit | `src/rate_limit_middleware.py`, `src/services/rate_limiter.py` |
| Deploy oficial | `docs/docs/get-started/docker.mdx` |
| Automatización | `Makefile` (`dev-cpu`, `test-os-jwt`) |
| Docling | `scripts/docling_ctl.py` |

---

## Orden de ejecución

1. Fase 1 — Valkey + `.env.example` + docs
2. Fase 2 — Local WSL smoke E2E
3. Fase 3 — VPS + TLS + hardening
4. Fase 4 — Flags Axioma + Langflow + Langfuse
5. Fase 5 — Enterprise cuando haya demanda

---

## Registro de verificación (automatizado)

<!-- Actualizado 2026-05-31 -->

| Verificación | Resultado |
|--------------|-----------|
| `docker compose config` | OK — `VALKEY_URL=redis://valkey:6379/0` en `openrag-backend` |
| `.env` local | Creado desde `.env.example` (gitignored; passwords dev — rotar en prod) |
| `docker compose up -d` | OK en Windows — 6 contenedores (`frontend:3000`, `langflow:7860`, `valkey`, etc.) |
| `GET /` y `GET /api/health` | HTTP 200 (smoke automatizado 2026-05-31) |
| Docling `:5001` | Manual — `uv run python scripts/docling_ctl.py start --port 5001` (WSL recomendado) |
| Ollama | Detectado en host Windows (`ollama` 0.24); en Compose usar `host.docker.internal:11434` |
| Smoke E2E | Manual tras stack healthy — tabla Fase 2 |
| VPS deploy | Documentado en Fase 3 (systemd, Caddy, ufw) |
| Fase 4 (Granite/Guardian/Langfuse) | Documentado en Fase 4 — activación opt-in en UI y `.env` |
