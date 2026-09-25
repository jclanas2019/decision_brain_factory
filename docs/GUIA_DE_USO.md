# Decision Brain 0.9: guía completa de uso y casos de uso

Esta guía describe las capacidades implementadas y cómo utilizarlas. Los comandos parten de la raíz del proyecto descomprimido, salvo indicación expresa. No necesitas leer documentos de versiones anteriores.

## 1. Qué hace el sistema

Decision Brain genera proyectos de clasificación de decisiones para un dominio. Cada cerebro tiene un contrato de entrada, una red local con varias salidas tipadas, reglas para proponer una acción, evaluación y versiones propias.

El modelo combina texto y campos numéricos. La búsqueda de configuraciones compara candidatos mediante validación; no es investigación autónoma ni RSI general. No usa la API de Jev ni acredita equivalencia con sus mecanismos internos.

| Componente | Responsabilidad |
|---|---|
| Fábrica | Generar proyectos independientes con contratos, configuración, pruebas y scripts |
| Cerebro | Producir probabilidades y proponer una acción según su contrato |
| Gateway | Autenticar, validar entradas/salidas, fijar versión y controlar idempotencia |
| Consumidor | Entregar eventos por rutas explícitas, con persistencia y reintentos limitados |
| Observador | Servir panel web, métricas, decisiones, auditoría y trazas |
| Harness | Comprobar escenarios y regresiones antes de aprobar un modelo |
| Registro de versiones | Guardar artefactos y verificar evidencia antes de activar |
| SDK Python | Integrar aplicaciones con gateway y observador sin escribir HTTP manualmente |

Una acción como `revision_humana` o `cola_postventa` es una propuesta. No existe un ejecutor conectado al ERP ni una bandeja completa donde personas aprueben y resuelvan casos. La revisión pendiente de un cerebro no se convierte automáticamente en un estado global del expediente.

## 2. Instalación y primer uso

El sistema completo requiere Python 3.12 o 3.13; se recomienda 3.12. La primera ejecución descarga dependencias fijadas. Los procesos locales están orientados a Linux y macOS; no se afirma compatibilidad nativa con Windows por el uso de locks POSIX y scripts Bash.

Extrae el ZIP en una carpeta nueva. No copies `.venv` de entregas anteriores ni mezcles archivos de varias versiones.

```bash
cd decision_brain_sdk
bash start.sh
```

El comando prepara un entorno aislado, ejecuta pruebas, entrena el ejemplo de comercio, comprueba la recarga del modelo, ejecuta el harness y genera HTML. El enlace al último informe queda en `report.html`; cada ejecución conserva su carpeta en `runs/`.

```bash
bash start.sh --no-open
bash start.sh check
```

El primero evita abrir el navegador. El segundo ejecuta las pruebas del software. Pasar las pruebas del software no equivale a aprobar el modelo.

| Salida del entrenamiento/harness | Interpretación |
|---|---|
| 0 | Cumple los criterios evaluados |
| 1 | El modelo incumple el harness; el informe se conserva |
| 2 | Fallo técnico o configuración inválida |

En macOS puedes abrir el último informe manualmente:

```bash
open report.html
```

### Actualizar conservando el entorno de la versión 0.8

Detén primero el supervisor anterior. Extrae esta versión en otra carpeta y apunta al mismo estado persistente; no copies ni borres su base, modelos o secretos:

```bash
bash start.sh operate --state "$HOME/Documents/2-lab-ai/decision_brain_factory/runtime/commerce-logistics"
```

Usa la ruta real de tu instalación. Mantener ese estado conserva auditoría, entregas pendientes y versiones. Indicar solo --projects-root crea un entorno nuevo en la carpeta de estado predeterminada de esta entrega: reutiliza proyectos, pero no migra su historial operativo. No ejecutes dos supervisores sobre el mismo estado.

Con un estado externo, pasa el mismo --state a status/example/submit. Para el ejemplo SDK usa --fleet con esa misma ruta. Si tenías launchd, detén la definición antigua y genera otra desde la instalación nueva; actualizar el ZIP no cambia su ProgramArguments automáticamente.

## 3. Elegir el modo de trabajo

| Necesidad | Comando | Persistencia |
|---|---|---|
| Entrenar y evaluar el ejemplo | `bash start.sh` | Guarda modelos e informes |
| Probar gates entre dos cerebros | `bash start.sh gates-demo` | Guarda resultados; cierra servicios al terminar |
| Explorar el panel con una demo | `bash start.sh observe-demo` | Mantiene la demo abierta hasta Ctrl+C; crea otra ejecución al repetir |
| Operar comercio y logística | `bash start.sh operate` | Reutiliza modelos, registro, cola y secretos |
| Generar otro cerebro | `bash start.sh new ...` | Crea un proyecto independiente |

El comando operate usa DEVELOPMENT y no levanta una flota productiva certificada. Un modelo con harness fallido puede observarse en este ambiente; las políticas de producción siguen rechazándolo.

## 4. Crear y utilizar un cerebro independiente

```bash
bash start.sh list
bash start.sh new --preset retail --brain-id comercio.triaje --out proyectos/comercio
bash start.sh new --preset logistica --brain-id logistica.incidencia --out proyectos/logistica
```

También existe el preset manufactura y se admite `--config` con un contrato propio. Si el destino existe, la fábrica se detiene: no sobrescribe proyectos.

```bash
(cd proyectos/comercio && bash start.sh)
(cd proyectos/logistica && bash start.sh)
```

Los paréntesis mantienen tu terminal en la carpeta original. Cada proyecto tiene sus propios contratos, suite, informes y configuración de gates. No queda conectado a otros por el hecho de crearlo.

| Archivo | Qué debes definir |
|---|---|
| `config/brain.json` | Campos de entrada, preguntas, opciones, umbrales, acciones y escenarios sintéticos |
| `config/harness_suite.json` | Casos de evaluación y resultados esperados |
| `config/promotion_policy.json` | Criterios mínimos y suites autorizadas para producción |
| `project.toml` | Rutas y umbral del harness |
| `config/gates/` | Identidad, contratos del borde, observabilidad y catálogo |

Para validar un contrato:

```bash
bash start.sh validate config/brain.json
```

Para predecir localmente con el último modelo guardado:

```bash
bash start.sh predict --state examples/example_state.json
```

Esta predicción local no atraviesa el gateway y, por tanto, no constituye una prueba de autenticación, auditoría central o interoperabilidad.

## 5. Interpretar entrenamiento, loss y evaluación

La pérdida de entrenamiento muestra el ajuste a los ejemplos vistos. La de validación permite seleccionar candidatos. La de prueba evalúa datos reservados. Una pérdida de entrenamiento muy pequeña con validación creciente es compatible con sobreajuste; no justifica declarar mejora.

Una propuesta rechazada no reemplaza a la mejor configuración. Si todas las propuestas posteriores son rechazadas, no hubo mejora demostrada en esa ejecución.

| Indicador | Cómo interpretarlo |
|---|---|
| Accuracy | Proporción de clases acertadas en el conjunto evaluado |
| Log loss | Penaliza probabilidades incorrectas; valores menores son mejores en la misma tarea |
| Matriz de confusión | Filas: clase real; columnas: clase predicha |
| Harness 4/4 | Cuatro escenarios cumplieron sus expectativas; no representa miles de casos independientes |
| Probabilidad máxima | Confianza del modelo para esa salida, no certeza objetiva |
| `needs_review` | El contrato exige revisión por confianza insuficiente |
| Fallback | No se cumplió una regla; se propuso la alternativa declarada |

Ejemplo: si “normal” tiene 42,7% y las alternativas 30,6% y 26,7%, “normal” es la opción más probable, pero puede quedar por debajo del umbral. La respuesta correcta del sistema puede ser `revision_humana`, no una afirmación de normalidad.

Los gráficos, matrices e interpretaciones están en el informe del modelo. La explicación de routing describe reglas configuradas y umbrales, no una explicación causal aprendida de la red.

### Evaluar una versión y comparar con una referencia

```bash
bash start.sh harness --run runs/candidato --suite config/harness_suite.json --output runs/evaluacion_candidato
bash start.sh harness --run runs/candidato --baseline runs/referencia --suite config/harness_suite.json --output runs/comparacion_candidato
```

Usa carpetas de salida nuevas. Los nombres son ejemplos: deben existir los modelos indicados. Una regresión es un caso que pasaba con la referencia y falla con el candidato.

`project.toml` admite únicamente `version` y `[harness]`:

```toml
version = 1
[harness]
suite = "config/harness_suite.json"
min_pass_rate = 1.0
# run = "runs/candidato"
# output = "runs/evaluacion_nueva"
# baseline = "runs/referencia"
```

Las rutas TOML se resuelven desde el archivo; los argumentos CLI explícitos prevalecen. Sin run se usa el último modelo completado. Sin output se crea una carpeta nueva.

## 6. Comercio y logística persistentes

```bash
bash start.sh operate
```

El primer arranque crea los proyectos que falten, reutiliza sus modelos si están completos, ejecuta el harness, registra copias development y prepara el catálogo. Si no hay modelo, entrena uno sintético. Los siguientes arranques no reentrenan ni adoptan candidatos nuevos silenciosamente.

Para conectar los proyectos de tu instalación anterior:

```bash
bash start.sh operate --projects-root "$HOME/Documents/2-lab-ai/decision_brain_factory/proyectos"
```

La carpeta debe contener `comercio/config/brain.json` y `logistica/config/brain.json`. Se verifican los campos esperados para este flujo; no se adaptan contratos arbitrarios automáticamente. También puedes indicar `--commerce` y `--logistics` por separado.

| Servicio | Puerto por defecto |
|---|---|
| Comercio | 8101 |
| Logística | 8102 |
| Gateway | 8103 |
| Panel/observador | 8104 |

El consumidor es un quinto proceso sin puerto HTTP. Todo escucha en localhost. `--base-port` permite elegir el primer puerto al crear otro entorno. `--state` permite otra carpeta de estado. Repetir las mismas rutas de proyectos es válido; cambiar a otros requiere otro estado.

La carpeta `runtime/commerce-logistics/` conserva configuración, modelos registrados, secretos, cola, logs y trazas. La definición guarda rutas absolutas: mover carpetas requiere revisar la configuración. Ctrl+C detiene los procesos y conserva los datos; repetir el comando recupera los eventos pendientes.

### Enviar un caso

En otra terminal, desde la raíz del mismo proyecto:

```bash
bash start.sh operate example --key caso-001
bash start.sh operate status
```

El ejemplo es ficticio y utiliza compra hace siete días. El segundo paso es asíncrono; consulta Traspasos entre cerebros en el panel. Repetir la misma clave no crea otra decisión.

Para enviar tus propios datos, guarda `caso.json`:

```json
{
  "brain_id": "logistica.incidencia",
  "context": {
    "horas_desviacion": 48,
    "estado_entrega": "La entrega sigue pendiente dos días después de lo acordado.",
    "contexto": "Seguimiento interno de un pedido."
  },
  "handoff": {"dias_desde_compra": 7}
}
```

```bash
bash start.sh operate submit --file caso.json --key pedido-123-evaluacion-1
```

`handoff` es un contrato auxiliar numérico de este flujo. Los días desde la compra deben provenir de la fuente de negocio; no se calculan a partir de las horas de retraso. Se validan campos exactos, finitud, rango no negativo y límites. No se permiten textos libres en handoff.

El evento transporta hechos autorizados. El gate de comercio reconstruye su propio contexto usando la edad de compra y una plantilla de seguimiento interno basada en la acción logística. No reenvía todo el contexto privado ni fabrica una cita del cliente.

### Estados de entrega

| Estado | Significado y actuación |
|---|---|
| Pendiente | Espera o reintento programado |
| Entregada | El destino respondió y se guardó su identificador |
| Requiere revisión (`dead`) | Error definitivo o intentos agotados; investigar antes de autorizar otra solicitud |

Las entregas son únicas por evento/ruta. Conservan versión destino, hash de ruta y clave de idempotencia. Los errores transitorios tienen un máximo de cinco intentos. Cambios de versión, contratos, identidad o ruta pueden requerir revisión. Los ciclos de rutas están prohibidos.

No cambies de clave para “forzar” un reintento: puede crear una nueva decisión. Una reserva ambigua no se elimina automáticamente. No existe todavía un asistente de reconciliación en la UI; el operador debe revisar la entrega y la reserva original. No edites la base mientras está en uso.

## 7. Panel web, métricas y OpenTelemetry

operate abre el panel con una URL privada de acceso local. El token va en el fragmento, se elimina de la barra y permanece solo en memoria. No compartas esa URL. Si recargas sin token, la pantalla solicita la credencial nuevamente.

| Vista | Qué muestra |
|---|---|
| Cerebros | Versión, calidad, semáforo y motivos |
| Tráfico | Solicitudes por minuto, aceptadas y rechazadas, con leyenda |
| Indicadores | Decisiones únicas, rechazos, p95 y revisión humana |
| Traspasos | Consumidor activo, entregas, intentos y errores |
| Decisiones | Acción, probabilidades máximas, regla y enlace a traza |
| Trazas | Spans gate, predict y judge, tiempos, padres y atributos permitidos |

La ventana operativa es la última hora. Decisiones y entregas se limitan a 100 filas recientes. El gráfico de solicitudes incluye reintentos; el contador de decisiones únicas no. Los percentiles incluyen rechazos y excluyen replays según las métricas del gateway. La disponibilidad observada con un solo caso no prueba estabilidad.

Verde significa controles locales satisfechos. Amarillo indica degradación o evidencia incompleta. Rojo indica calidad fallida, contrato/versionado inválido o indisponibilidad. Un cerebro verde no resuelve una revisión pendiente de otro. La recomendación de rollback es genérica: verifica que exista una versión anterior válida antes de ejecutarla.

Se usa OpenTelemetry real para trazas, con propagación W3C y exportador local SQLite. Se respetan las decisiones de muestreo del padre. La ausencia de spans no implica ausencia de una decisión auditada. No se guardan cuerpos, claves ni mensajes de excepción en atributos de spans.

```bash
export BRAIN_TELEMETRY_DB="$PWD/registry/telemetry.sqlite3"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="http://127.0.0.1:4318/v1/traces"
```

Estas variables deben estar definidas antes de iniciar los procesos. operate configura automáticamente un almacén común para su flota. El endpoint OTLP es opcional y requiere un colector ya disponible; el sistema no instala Jaeger, Tempo o Grafana. La UI local no consulta esos backends remotos automáticamente.

Las trazas locales tienen retención de siete días, aplicada durante exportaciones. No hay límite duro de tamaño ni compactación automática. Las métricas siguen disponibles en formato Prometheus y los logs/auditoría en JSON: esta versión no exporta métricas ni logs mediante OTLP.

La auditoría de decisiones tiene escritura transaccional y exportación JSONL con cadena de hashes. No es almacenamiento WORM ni protección frente a un administrador malicioso del disco. Mantén backups y una política de retención. SQLite y locks están pensados para un solo host, no para compartir WAL entre servidores.

## 8. Integración mediante SDK Python

El arranque del sistema instala el SDK junto al servicio. Para instalar solo el cliente en otra aplicación:

```bash
python -m pip install ./sdk
```

El paquete es `decision-brain-sdk`; el import es `decision_brain_sdk`. El SDK requiere Python 3.10 o superior y httpx; no instala numpy, entrenamiento ni servidor. No está publicado implícitamente en PyPI. Para instalar desde otra ubicación, indica la ruta local a la carpeta sdk.

### Integración local con el entorno persistente

```python
from decision_brain_sdk import DecisionClient, ObserverClient

with DecisionClient.from_fleet("runtime/commerce-logistics") as client:
    decision = client.predict(
        "logistica.incidencia",
        {
            "horas_desviacion": 48,
            "estado_entrega": "Entrega pendiente después de la fecha acordada.",
            "contexto": "Ejemplo ficticio de integración."
        },
        handoff={"dias_desde_compra": 7},
        idempotency_key="sdk-pedido-123-evaluacion-1"
    )
    print(decision.action, decision.needs_review, decision.trace_id)

with ObserverClient.from_fleet("runtime/commerce-logistics") as observer:
    print(observer.deliveries(decision.event_id))
```

from_fleet lee la configuración y los secretos locales existentes. No entrena, no arranca servicios ni accede al registro de otro equipo. La credencial del observador se mantiene separada de la del gateway. La lista de entregas puede estar vacía inmediatamente después de predecir porque el consumidor es asíncrono.

El ejemplo completo está en `examples/sdk_predict.py`:

```bash
.venv/bin/python examples/sdk_predict.py --key sdk-caso-001
```

### Integración remota

```python
import os
from decision_brain_sdk import DecisionClient

with DecisionClient(
    "https://gateway.mi-organizacion.example",
    os.environ["BRAIN_ORCHESTRATOR_TOKEN"],
    timeout=15
) as client:
    print(client.catalog())
```

La URL es ilustrativa; requiere un despliegue propio. Se exige HTTPS fuera de localhost y se verifica TLS por defecto. No se siguen redirecciones ni se heredan proxies del entorno. No se ponen credenciales en URLs. El SDK no crea un despliegue remoto.

### Reintentos e idempotencia

```python
from decision_brain_sdk import DecisionClient, TransportError

with DecisionClient.from_fleet() as client:
    request = client.prepare(
        "comercio.triaje",
        {"dias_desde_compra": 7, "mensaje": "Solicito información del producto.",
         "contexto": "Ejemplo ficticio."},
        idempotency_key="consulta-456"
    )
    try:
        result = client.send(request)
    except TransportError:
        # Tras comprobar conectividad, reutiliza exactamente request.
        # No generes otra clave ni cambies de versión para esquivar el error.
        raise
```

prepare copia el JSON a bytes inmutables y fija versión, clave y traza. send reutiliza esa solicitud. No hay reintentos automáticos: un timeout no demuestra que el servidor no haya decidido. Si vuelve a llamar a predict sin una versión explícita, podría descubrir una versión activa distinta; usa PreparedDecision cuando necesitas conservar la solicitud entre intentos dentro del proceso. El objeto no se guarda automáticamente entre reinicios.

La respuesta es un objeto Decision con request_id, brain_id, model_version, action, needs_review, trace_id, event_id, answers, confidence y replayed. `to_dict()` facilita su serialización. El SDK valida estructura, finitud y normalización de probabilidades; el gateway conserva la validación autoritativa del contrato y routing.

| Error SDK | Manejo |
|---|---|
| `ValueError` | Corrige argumentos antes de enviar |
| `TransportError` | Fallo de transporte; resultado potencialmente ambiguo, conserva la solicitud |
| `BrainError` con status | Rechazo HTTP; consulta status y request_id sin registrar secretos |
| `ProtocolError` | Respuesta inesperada; no ejecutes una acción a partir de ella |

Los mensajes de error del SDK no incluyen cuerpo de entrada, token ni contenido arbitrario del servidor. La referencia completa está en `SDK.md`. El SDK es síncrono; no incluye cliente async, JavaScript, streaming ni ejecución de acciones.

## 9. Casos de uso

### Caso A: consulta comercial independiente

Una aplicación recibe una consulta sobre un producto. Envía a comercio edad de compra, mensaje y contexto con una clave estable. El cerebro devuelve clasificación, prioridad, nivel y una acción propuesta. Si needs_review es true, la aplicación conserva el caso para una persona; no debe tratar la opción más probable como una decisión definitiva. No se envía automáticamente a logística.

Criterio funcional: mismo caso y clave producen el mismo request_id; el resultado y sus probabilidades se pueden consultar sin enviar otro caso.

### Caso B: incidencia logística con seguimiento comercial

El sistema conoce un retraso y la fecha de compra. Envía context logístico más handoff numérico. Logística propone una acción; el consumidor genera el traspaso; comercio recibe su propio estado validado. El panel permite seguir las dos decisiones mediante trace_id y comprobar la entrega.

Criterio funcional: un evento fuente genera como máximo una entrega por ruta; al reiniciar, la pendiente se recupera. Criterio de negocio pendiente: validar las plantillas y decisiones de toda la cadena con casos reales. Un harness local aprobado no sustituye esta evaluación.

### Caso C: incertidumbre en logística

El máximo de clasificación queda bajo el umbral y se propone revisión humana. El sistema registra esa incertidumbre. Comercio puede emitir una decisión adicional, pero eso no cancela la revisión de origen. La aplicación operadora debe impedir acciones automáticas mientras exista incertidumbre pendiente.

Limitación actual: no hay expediente global ni bandeja humana resolutiva. Deben añadirse antes de delegar acciones reales a la cadena.

### Caso D: caída del consumidor o de toda la flota

El gateway guarda un evento y el consumidor se detiene. El supervisor intenta reiniciarlo, hasta tres veces por minuto. Si se detiene todo, el próximo arranque recupera el cursor y las entregas pendientes. Las claves y versiones permanecen fijadas; un error definitivo queda visible para revisión.

Criterio funcional: recuperación sin perder el evento ni duplicar la decisión destino. No se garantiza alta disponibilidad entre hosts.

### Caso E: probar un candidato

Entrena una versión con datos representativos, ejecuta el harness contra una referencia y examina errores, calibración, grupos relevantes y matrices de confusión. Registra y activa solo después de aprobar evidencia. La búsqueda automática no publica modelos.

Criterio de aceptación: umbrales definidos por costos del negocio, suite autorizada y ninguna regresión prohibida. No se considera suficiente un resultado sintético 4/4.

### Caso F: crear otra industria

Define un contrato propio, sus preguntas y acciones, datos anotados y una suite pertinente. Genera con `start.sh new --config`. Puede operar independientemente; conectarlo requiere catálogo, ACL y mapping explícitos. El flujo operate de comercio/logística no adapta otros campos automáticamente.

## 10. Contratos y errores HTTP

POST /v1/predict requiere Bearer, Accept-Version, Idempotency-Key y traceparent. El cuerpo normal contiene brain_id y context; el flujo logístico persistente exige además handoff. El SDK construye los encabezados y permite fijar versión/traza.

| HTTP | Interpretación |
|---|---|
| 401 / 403 | Identidad ausente o acceso no autorizado |
| 404 | Recurso o cerebro inexistente |
| 409 | Versión, clave reutilizada con otro contenido o reserva pendiente |
| 413 | Tamaño, texto o magnitud excedidos |
| 422 | Contrato, traza, mapping o tipos inválidos |
| 429 | Límite de tasa |
| 500 | Respuesta interna inválida; no se inventa fallback |
| 503 / 504 | Indisponibilidad o timeout |

Límites predeterminados: 64 KiB, 12.000 caracteres por texto y magnitud 1e12; se aplica el límite más restrictivo del gateway y del cerebro. Los JSON libres, etiquetas de entrenamiento en context y campos adicionales son rechazados.

Un fallback declarado es una salida válida. Una respuesta inválida no debe convertirse en una cola inventada. El catálogo resuelve destinos y versiones; no se incluyen URLs de otros cerebros en el modelo.

## 11. Promoción, seguridad y continuidad

Antes de producción hacen falta datos reales representativos, revisión de dominio, aislamiento de evaluación, políticas de acceso, pruebas de carga y restauración. El comando operate está deliberadamente en desarrollo.

```bash
bash start.sh train --data data/real.csv --trials 5 --epochs 60 --output runs/candidato
bash start.sh harness --run runs/candidato --baseline runs/referencia --output runs/evaluacion_candidato
```

El CSV debe contener exactamente los campos del contrato, una columna `target__<id_de_decision>` por salida y `__split`. Ejemplo de encabezado de comercio:

```csv
dias_desde_compra,mensaje,contexto,target__clasificacion,target__atencion_prioritaria,target__nivel,__split
7,Solicito información del producto,Ejemplo ficticio,consulta,false,bajo,train
```

Esta fila ilustra el formato; no es un dataset suficiente. Las particiones son `train`, `validation`, `calibration` y `test`. Cada una necesita al menos diez filas y todas las clases de cada salida; no se admiten contextos idénticos entre particiones. Los mínimos técnicos no garantizan representatividad. Para obtener un archivo sintético de referencia:

```bash
bash start.sh generate --rows 2000 --seed 42 --output data/ejemplo_formato.csv
```

El generador no sobrescribe un archivo existente. No basta cambiar una marca synthetic a real. Revisa el esquema de tu contrato y el informe generado; los datos deben tener procedencia verificable.

Completa `config/evidence.example.json` en otro archivo. Incluye huella del dataset, revisor, fecha, separación, aceptación del negocio y SHA256 del report.json del harness. Autoriza la huella de la suite en `harness.approved_suite_sha256` de la política. La lista viene vacía. La política exige baseline salvo excepción inicial explícita y documentada.

```bash
.venv/bin/python -m decision_brain.releases --registry registry/production register --run runs/candidato --version v1 --environment production --harness runs/evaluacion_candidato/report.json --policy config/promotion_policy.json --evidence evidence.json
.venv/bin/python -m decision_brain.releases --registry registry/production activate --version v1 --environment production
```

Estos comandos son administrativos y requieren artefactos/evidencia reales. No deben ejecutarse para hacer pasar un ejemplo sintético. Para rollback, verifica que exista una versión previa aprobada:

```bash
.venv/bin/python -m decision_brain.releases --registry registry/production rollback --environment production
```

En operate, los registros development están bajo runtime/commerce-logistics/comercio/registry y logistica/registry; no los confundas con registry/production. Una entrega pendiente permanece ligada a su versión anterior y puede requerir reconciliación después de un cambio.

Los secretos locales del entorno tienen permisos 0600 y el estado 0700. Para acceso remoto necesitas TLS y una red administrativa o proxy adecuado. No hay SSO, roles por usuario ni aislamiento multitenant. Las plantillas Compose se incluyen, pero no reemplazan una validación de despliegue.

### Servicio persistente en macOS

Después de configurar operate una vez, detén el proceso foreground con Ctrl+C:

```bash
bash start.sh operate service-file
launchctl bootstrap "gui/$(id -u)" "$PWD/runtime/commerce-logistics/decision-brain.plist"
```

Para detenerlo:

```bash
launchctl bootout "gui/$(id -u)" "$PWD/runtime/commerce-logistics/decision-brain.plist"
```

La definición no contiene secretos. Para futuros inicios de sesión se puede instalar en ~/Library/LaunchAgents con su Label único. El proyecto no modifica launchd automáticamente. No ejecutes foreground y launchd sobre el mismo estado. Esta integración no se probó nativamente en macOS.

## 12. Resolución de problemas

| Síntoma | Qué revisar |
|---|---|
| Destino ya existe | Entra al proyecto existente; no repitas new sobre él |
| operate no encuentra proyectos | --projects-root debe apuntar al directorio que contiene comercio y logistica |
| Puerto ocupado | Detén otra instancia o crea otro estado con --base-port |
| Panel vacío | Comprueba catálogo, modelos activos y tráfico real; entrenar no registra tráfico del gateway |
| Cerebro rojo | Examina reasons; separa harness fallido de indisponibilidad técnica |
| Traspaso pendiente | Comprueba consumidor activo, next_attempt y logs |
| Traspaso requiere revisión | Examina versión, ruta, contrato y reserva; no cambies la clave para saltar el bloqueo |
| Sin spans | Comprueba muestreo, retención y BRAIN_TELEMETRY_DB compartida |
| HTTP 409 desde SDK | Conserva la solicitud preparada y revisa versión/clave/reserva; no reintentes con datos distintos |
| Error de instalación | Consulta runs/setup.log y setup_error.html si existe |

Logs persistentes: comercio.log, logistica.log, gateway.log, observer.log y consumer.log dentro del estado. No compartas secrets.json, URLs privadas del panel ni datos de clientes al pedir soporte.

La validación ejecutada y sus límites se documentan en `VALIDACION.md`. El sistema todavía necesita expediente global, revisión humana efectiva y adaptadores autorizados antes de ejecutar procesos reales de extremo a extremo.


## 13. Catálogo, servicios individuales y despliegue

operate configura un catálogo conjunto automáticamente. Para incorporar otro proyecto a un catálogo administrado manualmente:

```bash
.venv/bin/python -m decision_brain.catalog --project proyectos/otro --endpoint http://127.0.0.1:8200 --catalog config/gates/catalog.json --owner operaciones
```

El proyecto debe existir y tener su configuración de gates. La dirección es un ejemplo de worker local; define el puerto real. El CLI no sustituye silenciosamente un brain_id ya registrado. Revisa las ACL de llamadores en gateway.json, el secreto del worker por nombre de variable y las versiones registradas. Añadir el catálogo no crea rutas: config/gates/routes.json declara por separado origen, acción, destino y mapping. Usa hechos y literales revisados, no JSON interno compartido a ciegas.

| Proceso | Comando | Preparación necesaria |
|---|---|---|
| Worker | `bash scripts/serve.sh` | BRAIN_API_KEY, identidad y registro activo del modelo |
| Gateway | `bash start.sh gateway` | Catálogo, secretos de llamadores/workers y TLS en producción |
| Observador | `bash start.sh observer` | BRAIN_OBSERVER_TOKEN y config/gates/observer.json |

El observador individual sirve su UI en localhost:9100 por defecto. El gateway individual usa 8443 y certificados BRAIN_TLS_CERT/BRAIN_TLS_KEY cuando exige TLS. Estos puertos son distintos de los que usa operate. No inicies esos comandos esperando que descubran la flota runtime automáticamente: configura los archivos/env correspondientes o usa operate para el flujo integrado.

La plantilla `deploy/compose.yaml` incluye un worker, un gateway TLS y un observador. Requiere versión production aprobada y activada previamente. Configura secretos independientes BRAIN_STACK_WORKER_TOKEN, BRAIN_ORCHESTRATOR_TOKEN, BRAIN_POSTVENTA_TOKEN y BRAIN_OBSERVER_TOKEN mediante tu gestor de secretos. Coloca certificado y clave en secrets/tls/cert.pem y secrets/tls/key.pem. El UID 10001 debe leer los secretos y escribir los almacenes de auditoría/telemetría; los modelos se montan de solo lectura.

```bash
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
```

No ejecutes ese despliegue con secretos de ejemplo ni alteres procedencia para admitir modelos sintéticos. La plantilla no crea por sí sola una flota multiworker ni el consumidor persistente de operate. Debes adaptar topología, permisos, TLS y supervisión a la infraestructura. El build/arranque Docker no fue validado en esta entrega.

## 14. Lista de aceptación antes de un piloto real

| Área | Evidencia necesaria |
|---|---|
| Modelo | Casos reales independientes, umbrales de negocio y calidad por segmento |
| Cadena | Evaluación específica logística → comercio, incluyendo incertidumbre de origen |
| Personas | Responsable y procedimiento de revisión; no basta una etiqueta revision_humana |
| Efectos externos | Adaptadores autorizados, idempotencia y conciliación antes de ejecutar acciones |
| Acceso | Identidades, permisos, TLS y rotación de secretos |
| Continuidad | Pruebas de carga, backup/restauración y recuperación de pendientes |
| Operación | Alertas, capacidad, retención, mantenimiento y responsables definidos |

La puesta en marcha razonable comienza en paralelo sin efectos externos, sigue con operación asistida y solo automatiza clases de casos aprobadas. Esta guía describe el software disponible; no certifica un despliegue industrial ni elimina las limitaciones de calidad observadas.
