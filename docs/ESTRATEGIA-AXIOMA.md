# Estrategia Axioma 2.0 — Índice operativo

> Documento corto de navegación para la etapa actual.
> La evidencia detallada vive en audit, mejoras y deploy.

## Contexto

- Etapa actual: Parte I (estabilización y piloto técnico).
- Decisión macro vigente: **modelo A** (un VPS por cliente).
- Regla transversal: creación perezosa de documentos.

## Mapa de documentos

- Plan maestro: [`axioma_integral_completo_45ce1c44.plan.md`](c:\Users\Equipo\.cursor\plans\axioma_integral_completo_45ce1c44.plan.md)
- Principios: [`docs/mejoras/00-PRINCIPIOS.md`](./mejoras/00-PRINCIPIOS.md)
- Mejoras por dominio: [`docs/mejoras/`](./mejoras/)
- Auditoría: [`docs/PRODUCTION-READINESS-AUDIT.md`](./PRODUCTION-READINESS-AUDIT.md)
- Deploy: [`docs/PLAN-DEPLOY.md`](./PLAN-DEPLOY.md)

## Orden de ejecución

1. ~~`i0-principios`~~ (hecho)
2. `i2b-reingesta-runtime`
3. `i3-autopiloto`
4. Si el piloto pasa: `i4`–`i7`
5. Parte II (corpus) y Parte III (Go/No-go)

## Progreso

| Frente | Estado | Referencia |
|--------|--------|------------|
| i0-principios | Hecho | `docs/mejoras/00-PRINCIPIOS.md` |
| i1-diagnostico | Hecho | Plan maestro |
| i2-fix-rag | Hecho | `docs/mejoras/RAG-LANGFLOW.md` |
| i2b-reingesta-runtime | Hecho (768 OK) | OpenSearch `documents` → dim 768; ver `PLAN-DEPLOY` re-ingesta si hubo drift |
| i3-autopiloto | Bloqueado — falta balance | `docs/mejoras/AUTOPILOTO-PROTOCOLO.md` |
| i4–i7 | Hecho (código/docs) | `docs/mejoras/DEVOPS-SEGURIDAD.md` |
| Parte II/III | Plantilla lista | `docs/mejoras/PILOTO-VALIDACION.md` — **USER_ACTION_REQUIRED** |

## Criterios de priorización

- Primero RAG confiable sobre documentos reales; después plataforma.
- Deferidos con gatillo explícito (ver `00-PRINCIPIOS.md`).
- Operador configura; usuario final usa upload + chat.

## Ver también

- [`docs/PRODUCTION-READINESS-AUDIT.md`](./PRODUCTION-READINESS-AUDIT.md)
- [`docs/PLAN-DEPLOY.md`](./PLAN-DEPLOY.md)
- [`docs/mejoras/`](./mejoras/)
