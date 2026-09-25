# Gates de Decision Brain 0.6

## Arquitectura

El cliente llama a un gateway global. Este autentica al llamador, resuelve el cerebro en el catálogo, verifica la versión y el estado, llama al proceso privado y valida su respuesta. Un observador independiente exporta el registro central y calcula indicadores. La promoción se ejecuta offline mediante el CLI administrativo de releases; no se ejecuta el harness dentro de cada petición.

La fábrica conserva el entrenamiento, scaffolding, HTML, gráficos con leyendas, interpretaciones, harness y project.toml. Cada proyecto generado incluye `config/gates/`: contratos de entrada/salida en JSON Schema, políticas de interoperabilidad por ambiente, observabilidad, catálogo y rutas. `deploy/gates/` contiene las rutas equivalentes para contenedores.

## Prueba completa con un comando

```bash
bash start.sh gates-demo
```

Ejecuta dos modelos y cuatro procesos locales: dos workers, gateway y observador. Comprueba A → evento persistido → reconstrucción del contrato de B → decisión B. Cada ejecución tiene un directorio `runs/gates_*` con `report.html`, report.json, metrics.prom, operations.json, registros y auditoría. La ruta exacta se imprime al terminar. La calidad del modelo y las pruebas de integración se muestran por separado: un modelo de demostración puede fallar el harness, aunque la integración pase. Solo se usa el ambiente development.

## Contrato público

POST `/v1/predict`, Content-Type application/json. Encabezados obligatorios:

```
Authorization: Bearer <secreto-del-llamador>
Accept-Version: v3
Idempotency-Key: pedido-123-evaluacion-1
traceparent: 00-0123456789abcdef0123456789abcdef-0123456789abcdef-01
```

El cuerpo tiene exactamente `brain_id` y `context`; los campos de context deben corresponder al contrato del cerebro. El trace_id nace en el cliente/orquestador; el gateway exige un traceparent válido, conserva su trace_id y genera el span de la llamada al worker.

```json
{"brain_id":"logistica.incidencia","context":{"campos":"según config/brain.json"}}
```

Este es un ejemplo de estructura, no un estado logístico válido. El proyecto genera `examples/example_state.json` con sus campos reales. GET `/v1/catalog`, con autenticación, permite descubrir las versiones activas autorizadas sin exponer direcciones internas.

La respuesta contiene request_id, correlation_id, brain_id, model_version, context, answers, action, needs_review, confidence, trace_id y event_id. `context` es deliberadamente `{}`: no se repite texto personal. Las respuestas se validan por cabeza: catálogo exacto, tipos, probabilidades finitas y normalizadas, elección coherente con el máximo, umbral de revisión y regla de routing. Una respuesta defectuosa produce error controlado; no se inventa una acción para disimularlo. La revisión humana por baja confianza sí es una salida válida si está definida en el contrato.

| Condición | HTTP |
| --- | --- |
| Identidad ausente o inválida | 401 |
| Cerebro o evento no autorizado | 403 |
| Cerebro/evento inexistente | 404 |
| Schema, tipos o traza incorrectos | 422 |
| Cuerpo, texto o magnitud excedidos | 413 |
| Versión distinta, clave reutilizada con otro contenido o pendiente | 409 |
| Saturación por cuota | 429 |
| Respuesta interna inválida | 500 |
| Modelo/registro/integridad no disponible o saturación interna | 503 |
| Timeout del worker | 504 |

Límites por defecto: 64 KiB, 12.000 caracteres por texto y magnitud numérica 1e12. Se aplica el mínimo entre límite global y límite del cerebro. El gateway no acepta campos desconocidos ni claves JSON duplicadas.

## Idempotencia y eventos

SQLite conserva una reserva por ambiente, llamador, cerebro y clave. Un reintento idéntico devuelve la misma respuesta, request_id, trace_id y event_id, con `Idempotency-Replayed: true`; no produce otra inferencia ni otro registro de decisión. Cambiar contexto o versión con la misma clave produce 409. Dos solicitudes concurrentes no pueden reservar la misma clave. Una caída tras reservar deja la operación pendiente: se requiere reconciliación administrativa; no se reejecuta automáticamente. Es una garantía local de intento único, no ejecución exactamente una vez de acciones externas.

Una decisión válida escribe en una transacción su respuesta, auditoría y evento `decision.made`. Las rutas de `config/gates/routes.json` reconstruyen el estado destino con mapeos explícitos de hechos, respuestas categóricas y literales. Por defecto no se publican hechos; `event_facts` debe autorizar cada campo no textual y no redactado. No se reenvía el JSON privado del cerebro origen.

El CLI router descubre la versión por el catálogo público y llama al gate destino:

```bash
.venv/bin/python -m decision_brain.router --gateway https://localhost:8443 \
  --event-id ID_EVENTO --route-id ID_RUTA --brain-id postventa.triaje \
  --trace-id TRACE_ID_ORIGINAL --key caso-123-postventa
```

Lee `BRAIN_ORCHESTRATOR_TOKEN`. El llamador debe ser propietario del evento y estar autorizado para el destino. El gate exige la misma traza de origen. No se ejecutan acciones externas.

## Añadir cerebros al catálogo compartido

```bash
bash start.sh new --preset logistica --brain-id logistica.incidencia --out proyectos/logistica
.venv/bin/python -m decision_brain.catalog \
  --project proyectos/logistica --endpoint http://127.0.0.1:8001 \
  --catalog config/gates/catalog.json --owner operaciones
```

La fábrica no sobrescribe una carpeta existente. El catálogo no reemplaza silenciosamente un brain_id ya registrado. Incluye hash de contrato, acciones autorizadas, owner, SLA, endpoint, secreto del worker por nombre de variable y registro activo por ambiente. Ajuste las ACL de llamadores del gateway compartido para el nuevo cerebro. Sus workers solo conocen su propio modelo; las URLs viven en el catálogo.

El gateway vuelve a verificar el registro al predecir. Una modificación del contrato requiere actualizar intencionalmente el catálogo y sus schemas. `/ready` comprueba integridad, versión, identidad y hash contra los workers. Cada worker debe usar el BRAIN_ID exacto y su propio secreto interno; no exponga sus puertos fuera de la red privada.

## Observabilidad separada

`bash start.sh observer` inicia el proceso independiente en localhost:9100. GET `/metrics`, `/v1/operations` y `/v1/decisions` requieren `BRAIN_OBSERVER_TOKEN`. `/health` y `/ready` son sondeos sin credenciales. El gateway inicia mediante `bash start.sh gateway` en 8443; en producción exige TLS.

La auditoría de decisión central se exporta a `registry/audit.jsonl`, desde una tabla SQLite que rechaza UPDATE y DELETE. Incluye versión, contrato, probabilidades, regla y umbral aplicados, revisión, calidad del harness, request_id, trace_id y span del worker; nunca incluye el texto de entrada. Tiene cadena de hashes, bloqueo de exportador, fsync y recuperación de escritura parcial. No es un registro WORM firmado; un administrador del almacenamiento sigue siendo una autoridad de confianza. Respalde SQLite con su API de backup y archive el JSONL mediante un procedimiento administrado. No borre archivos WAL mientras estén en uso.

Las métricas incluyen decisiones por cerebro/versión/acción/revisión y rechazos por motivo, p50/p95 de latencia, tasa de revisión/fallback y probabilidad máxima media por cabeza. Los contadores son acumulados; percentiles y tasas corresponden a la última hora. No se calculan ECE online sin etiquetas posteriores. La consulta de decisiones permite filtrar cerebro y acción, devuelve el total de la última hora y hasta 100 registros; no es búsqueda por similitud semántica.

| Semáforo | Interpretación |
| --- | --- |
| Verde | Versión íntegra y activa, harness aprobado, worker listo, SLO observados satisfechos |
| Amarillo | Falta de tráfico/evidencia de SLO, degradación de SLO o marca shadow/canary |
| Rojo | Harness fallido, versión/contrato inválido o worker no listo |

El rojo recomienda revisar o volver a la versión previa. El rollback es una operación administrativa verificada, no un cambio automático por un pico transitorio. `shadow`/`canary` son marcas operativas; esta entrega no duplica tráfico ni reparte porcentajes. El campo shadow del audit queda null. Las reglas y umbrales explican el routing; no son una explicación causal aprendida por la red.
