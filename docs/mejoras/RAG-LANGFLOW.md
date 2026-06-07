# RAG + Langflow (alineación embeddings)

## Principios

- Un único origen de verdad para embeddings: `EMBEDDING_MODEL` + `EMBEDDING_PROVIDER`.
- El modelo de embedding no se define por intuición en Langflow; se propaga desde `.env` vía Compose.
- Cambiar embedding implica compatibilidad de dimensión y, por lo tanto, re-ingesta controlada.
- El modelo de chat y el de embedding son decisiones separadas.

## Estado actual (post-fix)

- `langflow` toma `SELECTED_EMBEDDING_MODEL` desde `EMBEDDING_MODEL` con fallback `nomic-embed-text`.
- `openrag-backend` recibe explícitamente `EMBEDDING_PROVIDER` y `EMBEDDING_MODEL`.
- `.env.example` documenta la compatibilidad de `SELECTED_EMBEDDING_MODEL` para evitar drift.

Referencia de auditoría: [Hallazgo #16](../PRODUCTION-READINESS-AUDIT.md).

## Anti-patrones

- Dejar `SELECTED_EMBEDDING_MODEL` apuntando a `text-embedding-3-small` mientras el stack usa Ollama.
- Cambiar `EMBEDDING_MODEL` sin re-ingestar índices existentes.
- Asumir que `LLM_MODEL` controla el retrieval o la dimensión vectorial.
- Validar solo por arranque de contenedores sin verificar dimensión/citas del índice.

## Criterio de hecho

Se considera correcto cuando:

1. El embedding efectivo en ejecución es `nomic-embed-text` (o el valor explícito de `EMBEDDING_MODEL`).
2. La dimensión del índice coincide con ese embedding.
3. Tras re-ingesta, las respuestas recuperan chunks del documento cargado (no de muestras previas).
