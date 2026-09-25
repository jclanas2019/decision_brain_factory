# SDK Python — referencia 0.9.0

Paquete instalable: `decision-brain-sdk`. Import: `decision_brain_sdk`. Cliente síncrono compatible con Python >=3.10; probado con Python 3.12. Requiere httpx >=0.28.1,<0.29. No requiere el paquete del servidor para integrarse por HTTP.

```bash
python -m pip install ./sdk
```

El paquete completo también expone el SDK después de `bash start.sh setup`. No se presupone publicación en PyPI. El cierre del cliente libera conexiones; utiliza `with` o `close()`.

## Clases

| Clase | Función |
|---|---|
| `DecisionClient(url, token, *, timeout=15, verify=True, transport=None)` | Acceso al gateway |
| `ObserverClient(url, token, *, timeout=15, verify=True, transport=None)` | Acceso al observador |
| `PreparedDecision` | Solicitud congelada para envío/reintento consistente |
| `Decision` | Resultado tipado y atributo replayed |
| `BrainError` | Rechazo HTTP o error de catálogo, con code/status/request_id |
| `TransportError` | Fallo de transporte; subclase de BrainError |
| `ProtocolError` | Respuesta incompatible; subclase de BrainError |

Los URL pueden incluir un prefijo de proxy, por ejemplo https://host/brain/. Fuera de localhost se exige HTTPS. No se permiten usuario/contraseña en URL, query ni fragmento. Por defecto se verifica el certificado, no se heredan proxies del entorno y no se siguen redirecciones. transport permite pruebas con httpx.MockTransport.

## DecisionClient

| Método | Resultado y comportamiento |
|---|---|
| `from_fleet(path="runtime/commerce-logistics", **kwargs)` | Lee fleet.json/secrets.json locales; usa credencial de orchestrator |
| `ready()` | GET /ready; no implica calidad global del negocio |
| `catalog()` | Lista de cerebros activos autorizados |
| `prepare(brain_id, context, *, idempotency_key, version=None, trace_id=None, handoff=None)` | Serializa el cuerpo y fija versión, clave y traza; descubre versión si no se indicó |
| `send(prepared)` | Envía una vez y valida la respuesta; nunca cambia la clave automáticamente |
| `predict(brain_id, context, **kwargs)` | Atajo para prepare + send |
| `prepare_event(event_id, route_id, brain_id, *, idempotency_key, trace_id, version=None)` | Prepara entrega manual al gate destino; requiere la traza original |
| `close()` | Cierra conexiones |

La clave de idempotencia es obligatoria y tiene hasta 128 caracteres alfanuméricos o `_.:-`. Los contextos deben ser JSON finitos y el cuerpo no puede exceder 64 KiB. El SDK no conoce todos los campos del contrato del modelo: los tipos/campos concretos y límites por cerebro se validan en el gateway.

trace_id es hexadecimal minúsculo de 32 caracteres no nulos; si se omite se genera uno. No se acepta un contexto OpenTelemetry de la aplicación automáticamente: para unir la llamada a una traza existente debes aportar trace_id. El SDK genera un span parent ID de propagación; no instrumenta por sí mismo un span cliente en tu aplicación.

Si el gateway indica replay, se conserva la traza de la respuesta original aunque el reintento haya llegado con otra. PreparedDecision se conserva en memoria y copia el cuerpo a bytes; no persiste solicitudes ni secretos en disco. Su serialización duradera, si se necesita, corresponde a la aplicación y debe proteger datos sensibles.

### Entrega manual de un evento

```python
from decision_brain_sdk import DecisionClient

with DecisionClient.from_fleet() as client:
    prepared = client.prepare_event(
        event_id="ID_DEL_EVENTO_ORIGEN",
        route_id="ID_DE_RUTA_CONFIGURADA",
        brain_id="comercio.triaje",
        idempotency_key="entrega-manual-caso-123",
        trace_id="0123456789abcdef0123456789abcdef"
    )
    # Enviar solo tras verificar esos valores y quién gestiona la entrega:
    # result = client.send(prepared)
```

No dupliques con este método una entrega que ya gestione el consumidor persistente. Distintas claves pueden crear distintas decisiones. La identidad del llamador debe coincidir con la del evento origen y tener autorización sobre el destino.

## Decision

Campos: request_id, brain_id, model_version, action, needs_review, trace_id, event_id, answers, confidence, replayed. `to_dict()` devuelve una copia serializable. La dataclass es frozen, pero sus diccionarios anidados no son inmutables; tratarlos como datos de lectura evita cambios accidentales en tu aplicación.

Se validan los campos básicos, cerebro y versión esperados, distribución finita/normalizada, elección coherente con la probabilidad máxima y confidence. Esto no reemplaza la validación del contrato completo del servidor, ni demuestra calibración, calidad del modelo o seguridad de una acción.

## ObserverClient

| Método | Consulta |
|---|---|
| `from_fleet(path="runtime/commerce-logistics", **kwargs)` | Configuración local con credencial independiente de observador |
| `ready()` | Disponibilidad del observador |
| `dashboard()` | Estado, indicadores, consumidor y entregas |
| `operations()` | Semáforo por cerebro |
| `decisions(brain_id, action=None)` | Hasta 100 decisiones de la última hora que coincidan con el filtro |
| `traces()` | Hasta 200 trazas recientes de la última hora |
| `trace(trace_id)` | Hasta 1000 spans; incluye indicador truncated |
| `metrics()` | Texto Prometheus |
| `deliveries(event_id=None)` | Filtra las últimas 100 entregas expuestas por dashboard |
| `close()` | Cierra conexiones |

No hay paginación SDK sobre un historial ilimitado. Una entrega ausente puede estar pendiente de descubrimiento o fuera de esa ventana/listado: no concluyas que nunca ocurrió. Consulta la auditoría/almacenamiento mediante procesos administrativos cuando corresponda.

## Errores y reintentos

```python
from decision_brain_sdk import BrainError, TransportError, ProtocolError

try:
    result = client.send(prepared)
except TransportError:
    # No sabemos si el servidor alcanzó a decidir. Conservar prepared.
    raise
except ProtocolError:
    # Respuesta no válida: no ejecutar ninguna acción.
    raise
except BrainError as error:
    print(error.code, error.status, error.request_id)
```

El SDK no introduce reintentos automáticos ni interpreta un 409 como permiso para generar otra clave. La política de backoff y reconciliación pertenece a la aplicación. Los ejemplos usan variables client/prepared ya creadas; consulta la guía principal para un programa completo.

## Alcance

No hay cliente async ni SDK JavaScript, batch, streaming, administración remota de modelos, login web, SSO o ejecutores de acciones. Tampoco se actualizan modelos mediante el SDK. Las operaciones administrativas continúan en los CLIs del servidor.
