# Piloto de Validación (Parte II + Parte III)

> Plantilla operativa para ejecutar validación real con documentos anonimizados.

## Estado

- `ii-corpus`: **scaffold listo**.
- `ii-ejecutar`: **scaffolded** (pendiente de ejecución real).
- `ii-informe`: **scaffold listo** (tablas vacías para completar).

## USER_ACTION_REQUIRED

- Aportar documentos reales anonimizados (no se incluyen en el repo).
- Ejecutar la ingesta y responder preguntas por documento.
- Completar tablas de scoring con resultados observados.

## Parte II — Corpus objetivo

| # | Tipo de documento | Qué valida | Documento real usado |
|---|-------------------|------------|----------------------|
| 1 | Balance anonimizado | Baseline contable | PENDIENTE |
| 2 | PDF escaneado/feo | OCR + robustez de ingesta | PENDIENTE |
| 3 | Notas al pie/anexo | Contexto largo y citas | PENDIENTE |
| 4 | Planilla con muchas columnas | Tablas y chunking | PENDIENTE |
| 5 | Documento no contable corto | Generalización | PENDIENTE |

## Protocolo de ejecución por documento

1. Registrar metadatos de ingesta (tiempo, páginas, errores).
2. Definir 3 preguntas antes de ver respuestas.
3. Evaluar retrieval, citas, exactitud numérica, utilidad y latencia.
4. Guardar evidencia mínima (pregunta + respuesta + cita).

## Plantilla de scoring por documento

### Documento 1 — [NOMBRE]

| Pregunta | Retrieval (0-2) | Citas (0-2) | Exactitud (0-2) | Utilidad (0-2) | Latencia | Observaciones |
|----------|------------------|-------------|------------------|----------------|----------|---------------|
| Q1 |  |  |  |  |  |  |
| Q2 |  |  |  |  |  |  |
| Q3 |  |  |  |  |  |  |

### Documento 2 — [NOMBRE]

| Pregunta | Retrieval (0-2) | Citas (0-2) | Exactitud (0-2) | Utilidad (0-2) | Latencia | Observaciones |
|----------|------------------|-------------|------------------|----------------|----------|---------------|
| Q1 |  |  |  |  |  |  |
| Q2 |  |  |  |  |  |  |
| Q3 |  |  |  |  |  |  |

### Documento 3 — [NOMBRE]

| Pregunta | Retrieval (0-2) | Citas (0-2) | Exactitud (0-2) | Utilidad (0-2) | Latencia | Observaciones |
|----------|------------------|-------------|------------------|----------------|----------|---------------|
| Q1 |  |  |  |  |  |  |
| Q2 |  |  |  |  |  |  |
| Q3 |  |  |  |  |  |  |

### Documento 4 — [NOMBRE]

| Pregunta | Retrieval (0-2) | Citas (0-2) | Exactitud (0-2) | Utilidad (0-2) | Latencia | Observaciones |
|----------|------------------|-------------|------------------|----------------|----------|---------------|
| Q1 |  |  |  |  |  |  |
| Q2 |  |  |  |  |  |  |
| Q3 |  |  |  |  |  |  |

### Documento 5 — [NOMBRE]

| Pregunta | Retrieval (0-2) | Citas (0-2) | Exactitud (0-2) | Utilidad (0-2) | Latencia | Observaciones |
|----------|------------------|-------------|------------------|----------------|----------|---------------|
| Q1 |  |  |  |  |  |  |
| Q2 |  |  |  |  |  |  |
| Q3 |  |  |  |  |  |  |

## Resumen de informe (pendiente)

| Métrica | Valor |
|---------|-------|
| Promedio retrieval + citas docs 1-4 | PENDIENTE |
| Alucinaciones numéricas graves | PENDIENTE |
| Top 3 cuellos de botella | PENDIENTE |
| Recomendación técnica | PENDIENTE |

---

## Parte III — Decisión Go/No-go (pendiente informe)

La decisión se completa cuando se cierre la tabla de resultados.

| Escenario | Condición | Decisión |
|-----------|-----------|----------|
| Go | Promedio docs 1-4 >= 1.5 en retrieval+citas y sin errores graves | PENDIENTE |
| Go con reservas | Balance OK pero falla documento feo/tablas | PENDIENTE |
| No-go | Fallas en docs base (1-2) o alucinación crítica repetida | PENDIENTE |

### Matriz de acción

| Resultado | Siguiente paso |
|-----------|----------------|
| Go | Avanzar a despliegue VPS modelo A |
| Go con reservas | Iterar Docling/chunking/modelo y repetir ronda |
| No-go | Volver a núcleo RAG (embedding/ingesta/retrieval) |
