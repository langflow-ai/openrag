# AUTOPILOTO - Protocolo Operativo

Estado: `BLOCKED_USER_DOC`

## Motivo del bloqueo
No se encontraron archivos de balance (`*.pdf` o `*.xlsx` con "balance" en nombre) en el workspace. Sin documento fuente no se puede ejecutar la re-ingesta orientada a balance ni validar preguntas financieras reales.

## Protocolo de ejecución (cuando llegue el documento)
1. Confirmar recepción del documento fuente y su periodo (mensual, trimestral, anual).
2. Copiar el archivo a una ruta versionada del proyecto (sin sobrescribir históricos).
3. Verificar stack activo: `docker info`, `docker ps`, OpenSearch en `https://localhost:9200`.
4. Re-ingestar en RAG/Langflow con chunking estable y embeddings `nomic-embed-text`.
5. Validar mapping del índice de documentos (`knn_vector`) con dimensión `768`.
6. Ejecutar smoke de recuperación con consultas semilla y revisar trazas.
7. Registrar resultados, gaps y acciones en este documento.

## Plantillas de preguntas (5)
1. "¿Cuál es el total de activos y su variación vs. el periodo anterior?"
2. "¿Cuál es el total de pasivos y cómo se distribuye entre corto y largo plazo?"
3. "¿Cuál es el patrimonio neto y qué cuentas explican su cambio principal?"
4. "¿Qué rubros concentran la mayor parte de costos/gastos operativos?"
5. "¿Qué señales de riesgo de liquidez se observan según el balance y notas?"

## Checklist mínimo de cierre
- [ ] Documento de balance cargado
- [ ] Re-ingesta finalizada sin errores
- [ ] Índice con dimensión 768 validada
- [ ] Smoke técnico y funcional OK
- [ ] Evidencias guardadas (logs/capturas/consultas)
