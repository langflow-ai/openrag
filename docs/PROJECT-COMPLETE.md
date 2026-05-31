# Axioma-2.0 (OpenRAG) — Proyecto Completo

> Documento maestro con toda la información del proyecto.
> Última actualización: 2026-05-31  
> **Deploy operativo:** ver [PLAN-DEPLOY.md](./PLAN-DEPLOY.md)

---

## Tabla de Contenidos

1. [Resumen del Proyecto](#1-resumen-del-proyecto)
2. [Stack Tecnológico](#2-stack-tecnológico)
3. [Arquitectura](#3-arquitectura)
4. [Características Implementadas](#4-características-implementadas)
5. [API Pública](#5-api-pública)
6. [Verticales de Negocio (B2B/B2C)](#6-verticales-de-negocio-b2bb2c)
7. [Gaps y Soluciones](#7-gaps-y-soluciones)
8. [Roadmap 2026](#8-roadmap-2026)
9. [SDD - Rate Limiting](#9-sdd---rate-limiting)
10. [Enlaces](#10-enlaces)

---

---

## 1. Resumen del Proyecto

**Axioma** (anteriormente **OpenRAG**) es una plataforma **RAG (Retrieval-Augmented Generation)** self-hosted de nivel empresarial basada en el código base de [langflow-ai/openrag](https://github.com/langflow-ai/openrag).

### 🎯 Lo que YA está resuelto (código base)

El código base incluye la mayoría del stack listo para **configurar y desplegar** (no implica producción sin `.env`, Ollama/Docling y smoke tests):

| Feature | Estado | Descripción |
|---------|--------|-------------|
| **Docling** | ✅ | OCR, chunking automático, preservación de jerarquía (títulos, tablas, gráficos) |
| **OpenSearch** | ✅ | Vector store + búsqueda híbrida con Reciprocal Rank Fusion (RRF) |
| **Langflow** | ✅ | Orquestación visual de agentes (drag-and-drop) — **chat RAG usa Langflow, no LLMRouter** |
| **APIs FastAPI** | ✅ | Backend `/v1/*`; cliente web vía frontend `/api/v1/*` |
| **MCP Server** | ✅ | Conexión nativa con Cursor y Claude Desktop |
| **OAuth/OIDC** | ✅ | Autenticación con Google, Microsoft |
| **API Keys** | ✅ | Autenticación para clientes API |
| **Conectores** | ✅ | OneDrive, SharePoint, S3, IBM COS |
| **Langfuse** | ✅ | Observabilidad — trazas + scores (Guardian/Ragas cuando se activan) |
| **Rate Limiting** | ✅ | Valkey + fallback en memoria. Tiers: free/pro/enterprise |
| **Valkey I/O threading** | ✅ | 4 threads, lazyfree eviction |
| **OpenSearch Hybrid + RRF** | ✅ | BM25 + KNN via Reciprocal Rank Fusion |
| **Ragas batch eval** | ✅ | Script `scripts/ragas_batch_eval.py` (cron opt-in) |
| **LLMRouter** | ⚠️ Módulo | `src/services/llm_router.py` existe; **no está en el path de chat** — usar Granite en Langflow |
| **Granite Guardian** | ⚠️ Opt-in | `GUARDIAN_ENABLED=false` por defecto |
| **HybridChunker** | ⚠️ Opt-in | `HYBRID_CHUNKER_ENABLED=false` por defecto |

### Tu trabajo como desarrollador

Tu misión se limita a:
1. **Configurar** el archivo `.env` con tus proveedores de modelos
2. **Diseñar** los agentes en Langflow (interfaz visual)
3. **Personalizar** el frontend (Next.js) con Vercel v0 para tu marca

---

## 2. Stack Tecnológico

| Capa | Tecnología |
|------|-------------|
| Backend | Python 3.13+, FastAPI, uvicorn, structlog |
| Frontend | Next.js, TypeScript, React |
| Database | OpenSearch 3.x (search + vector store) |
| Cache / Rate Limit | Valkey 9.x (con fallback en memoria) |
| AI Pipeline | Langflow |
| Auth | OAuth 2.0, OIDC, JWT (RS256), API Keys |
| Containers | Docker + Compose |
| Testing | pytest, pytest-asyncio, pytest-cov |

### AI/LLM Providers Soportados
- OpenAI (GPT-4, embeddings)
- Anthropic (Claude)
- IBM Watsonx
- Ollama (local)
- Embeddings: granite-embedding-278m-multilingual (12 idiomas)

---

## 3. Arquitectura

### Estructura del Proyecto

```
axioma-2.0/
├── src/                          # Backend Python
│   ├── main.py                   # Entry point
│   ├── api/                      # FastAPI endpoints
│   │   ├── auth.py, chat.py, documents.py, search.py
│   │   ├── flows.py, connectors.py, keys.py
│   │   └── v1/                   # API v1 pública
│   ├── services/                 # Lógica de negocio
│   │   ├── search_service.py     # Búsqueda semántica
│   │   ├── chat_service.py       # Chat RAG
│   │   ├── document_service.py   # Ingestión
│   │   ├── api_key_service.py    # API Keys
│   │   ├── rate_limiter.py       # Rate limiting (Valkey + fallback en memoria)
│   │   └── langflow_mcp_service.py
│   ├── connectors/               # Conectores externos
│   │   ├── base.py              # BaseConnector abstract
│   │   ├── onedrive/, sharepoint/
│   │   └── connection_manager.py
│   ├── rate_limit_middleware.py  # Starlette middleware — intercepta /v1/*
│   ├── session_manager.py        # JWT management
│   └── dependencies.py           # FastAPI dependencies
├── frontend/                     # Next.js app
├── sdks/                         # Python + TypeScript SDKs
├── tests/                        # Unit + Integration tests
├── flows/                        # Langflow configs
├── docker-compose.yml           # Full stack
└── Makefile                     # Automation
```

### Capas de la Arquitectura

```
┌─────────────────────────────────────────┐
│        API Layer (FastAPI)              │
│  /auth, /chat, /search, /documents      │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│          Service Layer                  │
│  DocumentService, SearchService, etc    │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│         Connector Layer                 │
│  OpenSearch, Langflow, APIs Externas    │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│        Infrastructure Layer             │
│   OpenSearch, Docker, Langflow          │
└─────────────────────────────────────────┘
```

### Flujo de Datos

**Ingestión:**
```
Upload → DocumentService → Processor → Chunking → Embedding → OpenSearch
```

**Búsqueda:**
```
Query → Embedding → OpenSearch k-NN → Results → Rank
```

**Chat RAG:**
```
User → ChatService → SearchService (context) → Langflow → Response
```

---

## 4. Características Implementadas

### ✅ Core RAG
- [x] Ingestión de documentos (PDF, texto, URL)
- [x] Chunking automático
- [x] Embedding multi-provider (OpenAI, Ollama, WatsonX)
- [x] Búsqueda semántica híbrida
- [x] Chat con RAG via Langflow
- [x] Knowledge filters (ACL)

### ✅ API v1 Pública
- [x] `/api/v1/search` — Búsqueda semántica
- [x] `/api/v1/chat` — Chat RAG
- [x] `/api/v1/documents` — Upload de documentos
- [x] `/api/v1/models` — Modelos disponibles
- [x] `/api/v1/knowledge_filters` — Filtros

### ✅ Autenticación
- [x] OAuth 2.0 (Google, Microsoft Graph)
- [x] OIDC support
- [x] JWT con RS256
- [x] API Keys management (`orag_xxxxx`)

### ✅ Conectores
- [x] OneDrive (OAuth, selective sync, webhooks)
- [x] SharePoint (OAuth, ACL per file)
- [x] S3 (buckets, filtros)
- [x] IBM COS (buckets, regional)
- [x] BaseConnector abstracto (extensible)

### ✅ Rate Limiting
- [x] Middleware Starlette (`rate_limit_middleware.py`) — intercepta `/v1/*`
- [x] Servicio Valkey con fallback en memoria (`services/rate_limiter.py`)
- [x] Tiers: free (100 req/min), pro (1000 req/min), enterprise (ilimitado)
- [x] Headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- [x] 15+ tests unitarios (`tests/unit/test_rate_limiter.py`)

### ✅ Infra & DevOps
- [x] Docker Compose (incluye Valkey 9.x con healthcheck)
- [x] Makefile automation
- [x] OpenSearch security
- [x] Docling integration

### ✅ Observabilidad
- [x] Langfuse integration (variables configuradas — observabilidad y evaluación activas)
- [x] Prometheus metrics
- [x] Structlog logging
- [x] Telemetry client

### ✅ Documentación
- [x] Swagger/OpenAPI (`/docs`)
- [x] FastAPI native

### ✅ MCP
- [x] Servidor MCP nativo via Langflow
- [x] Herramientas: chat, search, config

---

## 5. API Pública

### Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/v1/search` (cliente: `/api/v1/search` vía frontend) | POST | Búsqueda semántica |
| `/v1/chat` | POST | Chat RAG |
| `/v1/documents` | POST | Upload documento |
| `/v1/models` | GET | Modelos disponibles |
| `/v1/knowledge_filters` | GET | Filtros |
| `/v1/mcp/...` | GET | Servidor MCP |

### API Keys

- **Formato**: `orag_{random_32_chars}`
- **Hash**: SHA-256 para storage
- **Prefix display**: `orag_{first_8_chars}`

### Autenticación

```bash
Authorization: Bearer orag_xxxxxxxxxxxx
```

### Rate Limiting ✅

| Tier | Límite | Header |
|------|--------|--------|
| Free | 100 req/min | `X-RateLimit-Limit: 100` |
| Pro | 1000 req/min | `X-RateLimit-Limit: 1000` |
| Enterprise | Ilimitado | `X-RateLimit-Remaining: unlimited` |

Responde `429 Too Many Requests` con `Retry-After` cuando se excede el límite.
Store primario: Valkey 9.x. Fallback automático a memoria si Valkey no está disponible.

---

## 6. Verticales de Negocio (B2B/B2C)

### B2B — Casos de Uso

| # | Caso de Uso | Descripción |
|---|-------------|-------------|
| 1 | Knowledge Base Interno | Wiki corporativo, políticas |
| 2 | Soporte al Cliente B2B | Base conocimiento soporte |
| 3 | Asistente de Ventas | Documentación productos |
| 4 | Gestión Documental | Búsqueda contratos |
| 5 | Compliance/Regulatorio | Docs regulatorios |
| 6 | Help Desk IT | Knowledge base tickets |

### B2C — Casos de Uso

| # | Caso de Uso | Descripción |
|---|-------------|-------------|
| 1 | Customer Support Chatbot | FAQ, troubleshooting |
| 2 | Product Documentation | Manuales, guías |
| 3 | Chat de Ventas | Pre-sales |
| 4 | Community Q&A | Foro interno |
| 5 | User Guide/Manual | Docs interactivos |

### Estado por Vertical

| Vertical | Listo | Faltante |
|----------|-------|----------|
| **B2B** | 60% | SSO, Audit, White-label |
| **B2C** | 100% | — |

---

## 7. Gaps y Soluciones

### B2B

| Gap | Solución |
|-----|----------|
| SSO/SAML | IdP (Auth0/Keycloak) + OpenSearch SAML |
| Audit Logs | OpenSearch Audit Logs nativo |
| Permisos granulares | DLS + FLS |
| White-label | Fork + Vercel v0 en /frontend |

### B2C

| Gap | Solución |
|-----|----------|
| Caching | Valkey LangCache (futuro) |
| Analytics | ✅ Langfuse configurado — observabilidad y evaluación activas |
| Rate Limiting | ✅ Implementado — `src/rate_limit_middleware.py` |
| Multi-language | granite-embedding + reranker |

---

## 8. Roadmap 2026

### Fase 0: Migración Redis → Valkey ✅ COMPLETA (2026-04-14)

```
[x]    RateLimiter migrado a Valkey 9.x (BSD-3-Clause)
[x]    SemanticCache migrado a Valkey 9.x
[x]    docker-compose actualizado (valkey/valkey-bundle:latest)
[x]    Tests + docs actualizados
```

### Fase 1: Infraestructura ✅ COMPLETA (2026-04-15) — commit db2495f4

```
[x]    Valkey I/O threading (--io-threads 4, lazyfree)
[x]    OpenSearch hybrid query + RRF normalization pipeline
[x]    Ragas batch eval nocturno (scripts/ragas_batch_eval.py)
```

### Fase 2: Capacidades de Modelo ✅ Código (2026-04-15) — activación opt-in

```
[x]    LLMRouter (src/services/llm_router.py) — módulo listo; chat usa Langflow, no este router
[x]    Granite Guardian 3.3 async guardrail (src/services/guardrail_service.py) — GUARDIAN_ENABLED=false default
[x]    HybridChunker + Context Expansion — flags OFF; requiere re-ingesta
```

### Fase 3: Diferenciación Enterprise (Q2-Q3 2026)

```
[ ]    SGLang backend (GRANITE_BACKEND=sglang) — RadixAttention para MoE
[ ]    Self-RAG / CRAG patterns en Langflow (nodos de reflexión)
[ ]    Valkey HEXPIRE per-field TTL para memoria de sesión multi-agente
[ ]    Multi-agent Langflow + MCP externo (Slack, SQL, Jira)
[ ]    Grafana AIOps dashboards (FastAPI + OpenSearch + Valkey)
[ ]    OpenSearch Dashboards — DLS/FLS, ISM, UBI, alertas (ver detalle abajo)
```

#### OpenSearch Dashboards — Cuarto de Máquinas

Marco arquitectónico:
- **Fachada** → Frontend Next.js (cliente final)
- **Fábrica de cerebros** → Langflow (lógica de IA, agentes)
- **Cuarto de máquinas** → OpenSearch Dashboards (infra/ops)

**Regla de oro:** Toda IA vive en Langflow. Dashboards es solo para infraestructura y seguridad.

| # | Feature | Código | Prioridad |
|---|---------|--------|-----------|
| 1 | DLS/FLS multi-tenant | ❌ Solo config | Q2 2026 — antes de primer cliente B2B |
| 2 | ISM — index lifecycle | ❌ Solo config | Q2 2026 |
| 3 | Alertas + Monitoreo (Slack webhook) | ❌ Solo config | Q2 2026 |
| 4 | Search Relevance Workbench | ❌ Solo config | Q2-Q3 2026 |
| 5 | ML Commons — embedding registry | ❌ Casi config | Q3 2026 |
| 6 | UBI — User Behavior Insights | ⚠️ 1 hook en search_service.py | Q3 2026 |
| 7 | OpenSearch Assistant (DevOps) | ❌ 1 config flag | Q3 2026 |

**Anti-patrón:** NO construir flujos de agentes o prompts en Dashboards — fragmenta arquitectura y rompe trazabilidad Langfuse.

### Fase 4: On-demand del cliente (Q3-Q4 2026)

```
[ ]    Granite Vision 3.3-2B para charts/infografías (DocVQA 0.91)
[ ]    Bounding boxes en PDF (PDF.js overlay con coordinate tokens)
[ ]    Ragas TestsetGenerator por cliente
[ ]    Pathway para ingesta en tiempo real (streams hacia OpenSearch)
```

---

## 9. Rate Limiting — Implementación

### Archivos

| Archivo | Descripción |
|---------|-------------|
| `src/rate_limit_middleware.py` | Middleware Starlette — intercepta `/v1/*`, extrae API key, aplica límites |
| `src/services/rate_limiter.py` | Servicio Valkey con fallback en memoria y cache de tiers (TTL 5 min) |
| `tests/unit/test_rate_limiter.py` | 15 tests unitarios (TDD) |
| `src/config/settings.py` | Variables `VALKEY_URL`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW`, `RATE_LIMITS` |
| `docker-compose.yml` | Servicio `valkey/valkey-bundle:latest` con healthcheck y volumen persistente |
| `pyproject.toml` | Dependencia `redis[asyncio]>=5.0.0` |

### Diseño

- **Extracción del API key**: header `X-API-Key` o `Authorization: Bearer orag_...`
- **Valkey key**: `rate_limit:{sha256(api_key)}` — nunca el key en crudo
- **Tier resolution**: memoria (TTL 5 min) → OpenSearch → default `free`
- **Fallback**: si Valkey no responde, counters en memoria (single-process)
- **Enterprise**: cortocircuita antes de tocar Valkey (siempre permitido)

---

## 10. Enlaces

### Repositorio
- GitHub: `javi2481/Axioma-2.0`

### Documentación del Proyecto
- `/docs/ROADMAP-2026.md` — Roadmap maestro
- `/docs/specs/api-rate-limiting.md` — Spec
- `/docs/specs/api-rate-limiting-design.md` — Design
- `/docs/specs/api-rate-limiting-tasks.md` — Tasks

### API
- Swagger: `/docs` (cuando el servidor corre)

### Métricas Objetivo 2026

| Métrica | Target |
|---------|--------|
| Uptime | 99.9% |
| Latencia search | <200ms (p95) |
| Latencia chat | <3s (p95) |
| API Keys activas | 100+ |
| Clientes enterprise | 5+ |

---

*Documento vivo — actualizar conforme evoluciona el proyecto*
*Creado: 2026-04-13 | Última actualización: 2026-04-14*
