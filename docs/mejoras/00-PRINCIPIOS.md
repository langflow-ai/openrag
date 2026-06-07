# 00 - Principios Operativos Axioma

> Documento rector corto para decisiones de implementación y operación.
> Relacionado: [ESTRATEGIA-AXIOMA.md](../ESTRATEGIA-AXIOMA.md), [PLAN-DEPLOY.md](../PLAN-DEPLOY.md), [PRODUCTION-READINESS-AUDIT.md](../PRODUCTION-READINESS-AUDIT.md).

## 1) Regla de oro de documentación

- `PRODUCTION-READINESS-AUDIT.md`: evidencia y hallazgos.
- `docs/mejoras/*`: diseño aplicado por tema.
- `ESTRATEGIA-AXIOMA.md`: orden de ejecución y priorización.
- `PLAN-DEPLOY.md`: operación paso a paso.

## 2) Configuración en datos, comportamiento en código

- Evitar hardcode de defaults de negocio en frontend/backend.
- Preferir `.env` + `config/` para parámetros operativos.
- Cambios de proveedor/modelo deben quedar trazables en configuración.

## 3) Anti-hardcode como política

- Nada de mensajes o nudges ligados a "OpenRAG" en onboarding de Axioma.
- `INGEST_SAMPLE_DATA` debe arrancar en `false`.
- `DEFAULT_DOCS_URL` debe permanecer vacío/comentado salvo caso explícito.

## 4) `env_file` solamente en backend

- `openrag-backend` es la fuente canónica de lectura de `.env`.
- Langflow mantiene lista explícita de variables permitidas.
- Este criterio reduce drift y evita sobreexposición accidental.

## 5) Modelo de despliegue A (un VPS por cliente)

- Priorizar aislamiento por despliegue sobre multi-tenant prematuro.
- Seguridad y reproducibilidad primero, automatización enterprise después.
- La complejidad multi-tenant se activa por gatillo de negocio real.

## 6) Creación perezosa de documentos

- Crear docs de mejora solo cuando hay implementación concreta.
- Evitar documentos largos adelantados sin evidencia operativa.
- Mantener cross-links mínimos entre audit, estrategia y deploy.

## 7) Operador vs usuario final

- El operador configura onboarding y parámetros sensibles por entorno.
- El usuario final interactúa con upload + chat, sin tocar embeddings.
- Gateo por rol se eleva cuando haya más de un usuario por tenant.

## 8) Re-ingesta obligatoria ante cambio de embedding

- Si cambia proveedor/modelo/dimensión, se re-ingiere corpus completo.
- No se da por válido por "arrancó el contenedor": se valida retrieval.

## 9) Seguridad operativa antes de exponer VPS

- Secretos generados fuera del repo y nunca commiteados.
- Puertos internos no públicos (9200, 6379, 7860).
- Frontend detrás de reverse proxy con TLS.

## 10) Deferidos con gatillo explícito

- Cada postergación debe incluir motivo y condición de reactivación.
- Sin gatillo, no se reabre discusión de prioridad.
# 00-PRINCIPIOS — Axioma 2.0

> Guía corta para ejecutar sin drift, sin sobre-ingeniería y con foco en validación real.
> Estado: vigente para Parte I del plan integral.

## Bloque 1 — Regla de oro documental

**Modelo:** Auto (Cursor)  
**Rol:** orquestar documentación sin duplicación  
**Por qué:** evitar ruido y mantener una sola fuente de verdad por tema

- **Audit** (`docs/PRODUCTION-READINESS-AUDIT.md`): evidencia, hallazgos y severidad.
- **Mejoras** (`docs/mejoras/`): decisiones y diseño aplicado por dominio.
- **Estrategia** (`docs/ESTRATEGIA-AXIOMA.md`): índice de navegación y estado.
- **Deploy** (`docs/PLAN-DEPLOY.md`): operación paso a paso.

Si una idea ya existe en otro documento, se referencia con link; no se copia.

## Bloque 2 — Config en datos, no en código

**Modelo:** Auto (Cursor)  
**Rol:** definir límites de configuración  
**Por qué:** reducir drift entre `.env`, compose y runtime

- Parámetros de operación van en `.env`/compose/config persistida.
- Código expresa comportamiento y validaciones, no valores de negocio hardcodeados.
- Cambios de proveedor, modelo o endpoint deben resolverse por configuración.

## Bloque 3 — No hardcodear

**Modelo:** Auto (Cursor)  
**Rol:** fijar convención de implementación  
**Por qué:** permitir fork mantenible y cambios sin refactor costoso

- Evitar defaults engañosos que oculten errores de entorno.
- Evitar strings de producto upstream en UX final si el contexto es Axioma.
- Evitar acoplar prompts, seeds o flujos a un único caso demo.

Regla práctica: si un operador razonable querría cambiar un valor, ese valor no debe quedar fijo en código.

## Bloque 4 — `env_file` solo en backend

**Modelo:** Auto (Cursor)  
**Rol:** decidir alcance de carga de entorno  
**Por qué:** balancear robustez del backend con control explícito en Langflow

- Backend: permitido usar `env_file` para minimizar omisiones de variables críticas.
- Langflow: mantener lista explícita de variables permitidas.
- Resultado esperado: menos drift sin abrir pasarela indiscriminada de variables en todos los servicios.

## Bloque 5 — Modelo A primero

**Modelo:** Auto (Cursor)  
**Rol:** definir foco de despliegue  
**Por qué:** priorizar revenue y validación real antes de complejidad multi-tenant

- **Modelo A:** un VPS por cliente, aislamiento simple y argumento comercial claro.
- Multi-tenant compartido se evalúa solo cuando exista dolor operativo real.
- La priorización de backlog debe seguir este orden.

## Bloque 6 — Creación perezosa de docs

**Modelo:** Auto (Cursor)  
**Rol:** controlar timing documental  
**Por qué:** evitar producir documentos que envejecen antes de usarse

- Se crea un documento cuando el cambio que describe empieza o termina.
- No abrir ramas completas de documentos "por si acaso".
- Mantener trazabilidad con enlaces cortos entre audit, mejoras y deploy.

## Bloque 7 — Deferidos con gatillos de reactivación

**Modelo:** Auto (Cursor)  
**Rol:** gestionar backlog postergado  
**Por qué:** postergar sin perder contexto ni repetir discusiones

Cada deferido debe tener:

1. motivo explícito de postergación;
2. gatillo objetivo para reactivarlo;
3. documento donde se registrará su retorno.

Sin gatillo, el deferido no está bien definido.

## Bloque 8 — Operador vs usuario final

**Modelo:** Auto (Cursor)  
**Rol:** separar responsabilidades del producto  
**Por qué:** evitar complejidad de UX prematura en etapa de validación

- **Operador:** configura stack, onboarding técnico, embedding y despliegue.
- **Usuario final:** sube documentos y consulta; no toca settings sensibles.
- Cualquier apertura de settings al usuario final requiere control por rol y un gatillo de negocio.

## Cierre operativo

Antes de crear nuevas tareas: verificar que respeten estos principios. Si no respetan al menos 6 de 8 bloques, se replantea alcance.
