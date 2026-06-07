# DEVOPS y Seguridad Operativa

> Endurecimiento mínimo antes de exponer un VPS con datos de cliente.
> Relacionado: [PLAN-DEPLOY.md](../PLAN-DEPLOY.md), [PRODUCTION-READINESS-AUDIT.md](../PRODUCTION-READINESS-AUDIT.md).

## Perfiles Compose

- **Desarrollo local:** `docker-compose.yml`
  - Puertos de observabilidad y debug disponibles localmente.
  - Útil para iteración rápida.
- **Producción ligera:** `docker-compose.yml` + `docker-compose.prod.yml`
  - Frontend bind a `127.0.0.1:3000`.
  - Sin exposición pública de `9200`, `6379`, `7860`.
  - `env_file: .env` aplicado solo en `openrag-backend`.
  - Valkey con `--requirepass`.

Comando recomendado:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Secretos

- Generar secretos con `scripts/generate-secrets.sh`.
- Completar `.env` con:
  - `OPENSEARCH_PASSWORD`
  - `OPENRAG_ENCRYPTION_KEY`
  - `LANGFLOW_SECRET_KEY`
  - `SESSION_SECRET`
  - `VALKEY_PASSWORD` (obligatorio en overlay prod)
- Nunca commitear secretos reales.

## Preflight operativo

Ejecutar antes de levantar o validar entorno:

```bash
scripts/preflight.sh
```

Chequeos mínimos:

- Variables críticas presentes en `.env`.
- Stack saludable (`/api/health`, OpenSearch, Valkey).
- Dimensión vectorial consistente con el embedding esperado.

## Política de embeddings

- Cambiar `EMBEDDING_MODEL` o proveedor implica re-ingesta total.
- La validez se confirma con retrieval real, no solo con contenedores "healthy".

## USER_ACTION_REQUIRED

- Definir valores reales y robustos en `.env` para producción.
- Ejecutar preflight sobre el entorno final antes de abrir acceso externo.
