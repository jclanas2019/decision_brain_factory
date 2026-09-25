# Observabilidad y UI Web · 0.7.0

## Uso inmediato

Desde la raíz del proyecto completo:

```bash
bash start.sh observe-demo
```

La demo prepara dos modelos sintéticos y sus registros development. Inicia dos procesos de inferencia, el gateway y el observador. Ejecuta decisiones A → B, comprueba reintentos y rechazo de versión, verifica spans reales del SDK y abre el panel. Continúa funcionando hasta Ctrl+C. Para evitar abrir el navegador: `bash start.sh observe-demo --no-open`.

La URL usa un puerto local disponible y un token temporal en el fragmento `#token=`. El navegador elimina el fragmento inmediatamente y conserva la credencial solo en memoria. No se envía como query string, no se guarda en localStorage y no aparece en los logs HTTP. La terminal sí muestra esa URL para poder abrirla manualmente: no la compartas. Al recargar, introduce el token de esa URL o abre de nuevo la URL original. Todos los procesos escuchan en localhost. Este acceso automático está limitado a la demo; no sustituye la gestión de identidad de producción.

La demo realiza tráfico inicial finito, no simula actividad continua. El panel consulta cada cinco segundos los datos reales guardados; no inventa decisiones ni cambia semáforos para aparentar actividad. Los modelos logísticos pueden fallar el harness y aparecer en rojo aunque la comunicación funcione.

## Panel para un entorno existente

```bash
export BRAIN_OBSERVER_TOKEN="TU_SECRETO_ALEATORIO_DE_AL_MENOS_32_CARACTERES"
bash start.sh observer
```

Abra http://127.0.0.1:9100 e introduzca el secreto. No use el texto de ejemplo como credencial. El proceso usa `config/gates/observer.json`; el valor por defecto apunta a producción, que necesita catálogo, versiones activas y workers disponibles. Entrenar una carpeta no equivale a registrar o activar un cerebro. El panel no incorpora automáticamente proyectos creados con la fábrica.

| Vista | Qué permite interpretar |
| --- | --- |
| Estado | Versión verificable, semáforo y causa, separando disponibilidad de calidad |
| Indicadores | Decisiones únicas, rechazos HTTP, p95 y tasa de revisión |
| Gráfico de tráfico | Solicitudes aceptadas y rechazadas por minuto con leyenda y ejes |
| Decisiones | Acción, probabilidades máximas, regla y acceso a la traza |
| Trazas | Servicio, span, padre, duración, estado y atributos permitidos |

El filtro de cerebro afecta indicadores, gráfico, estado y decisiones. Los indicadores cubren la última hora; la tabla contiene como máximo las 100 decisiones más recientes del conjunto. La gráfica incluye reintentos; el contador de decisiones únicas no. Los spans se muestran como barras temporales relativas y con su ID de padre explícito. No hay botones de promoción, rollback ni ejecución de acciones en la UI.

## OpenTelemetry real

Se usa opentelemetry-api/sdk 1.38.0 y el exportador oficial OTLP/HTTP. La instrumentación manual ASGI crea spans SERVER `gate` y `predict`; el proceso de inferencia añade `judge`. El gateway inyecta el contexto W3C activo en traceparent y el worker lo extrae. La traza se correlaciona con el request_id de la auditoría. En eventos A → B se conserva la traza común; los dos gates pueden ser hermanos bajo el contexto del orquestador, no se inventa una relación causal padre-hijo que no fue propagada.

Los spans contienen exclusivamente método/ruta normalizada/estado HTTP, identificadores de cerebro, versión y solicitud, acción y regla cuando están disponibles. No se capturan cuerpos, encabezados de autorización, texto del cliente, queries ni mensajes de excepción. Los rechazos 4xx llevan su estado HTTP; los fallos 5xx se marcan ERROR. Las consultas periódicas de la propia UI se omiten para no llenar el listado con sus refrescos.

Por defecto, el muestreo del SDK es parent-based; respeta el bit sampled entrante y las variables OTEL_TRACES_SAMPLER/OTEL_TRACES_SAMPLER_ARG. Un padre no muestreado no produce spans locales ni OTLP. La auditoría de decisiones es independiente y no se muestrea. La ausencia de spans no prueba que no hubo decisión.

El exportador local del SDK guarda spans en SQLite y permite consultarlos sin infraestructura externa. Configure la misma ruta absoluta BRAIN_TELEMETRY_DB en todos los procesos del mismo host:

```bash
export BRAIN_TELEMETRY_DB="$PWD/registry/telemetry.sqlite3"
```

La demo lo configura automáticamente. Sin esa variable, cada proceso usa registry/telemetry.sqlite3 relativo a su directorio de trabajo: procesos lanzados desde carpetas distintas no compartirán trazas automáticamente. La retención es de siete días, limpiada durante exportaciones; no hay límite duro por tamaño ni compactación automática. Para gran volumen utilice un backend externo y una política operativa de almacenamiento. Las trazas son best effort: un fallo del exportador no cambia la decisión; no equivalen al registro transaccional de auditoría.

## Exportación OTLP/HTTP

Para exportar además a un colector o backend compatible, defina antes de arrancar cada proceso:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="http://127.0.0.1:4318/v1/traces"
bash start.sh observe-demo
```

Ese colector debe estar disponible. Alternativamente OTEL_EXPORTER_OTLP_ENDPOINT define la base y se añade /v1/traces. El envío externo usa BatchSpanProcessor y timeout de tres segundos; la vista local sigue disponible si el colector falla. El SDK admite las variables estándar de headers y certificados del exportador HTTP; gestione esos secretos fuera del repositorio. En varios hosts, envíe los spans a un colector central: no comparta SQLite WAL mediante un filesystem de red. La UI incluida lee el almacén local, no consulta automáticamente un Jaeger/Tempo remoto.

Esta entrega instrumenta **trazas OpenTelemetry**. Conserva las métricas de negocio en `/metrics` con formato Prometheus y los logs/auditoría JSON existentes; no afirma exportar métricas o logs mediante el SDK de OpenTelemetry. Un colector, Prometheus o Grafana no se instala ni inicia implícitamente.

## Seguridad y despliegue

La página y sus assets no contienen información privada. Todas las consultas de datos exigen Bearer, devuelven no-store y se sirven desde el mismo origen. Sin CDNs ni dependencias JavaScript externas. CSP restringe scripts, conexiones y framing. El logout elimina la credencial; una pestaña abierta mantiene acceso mientras el secreto sea válido. No se implementan SSO, roles por usuario o sesiones de servidor.

El observador escucha en localhost; para acceso remoto use TLS y una red administrativa o proxy de autenticación. No publique HTTP con credenciales en una red insegura. Compose incluye un volumen de telemetría común y la variable de endpoint OTLP para los tres servicios; el directorio debe ser escribible por UID 10001. El puerto del observador permanece ligado a localhost.

## Fuentes y alcance

Instrumentación: https://opentelemetry.io/docs/languages/python/instrumentation/

Exportadores: https://opentelemetry.io/docs/languages/python/exporters/

Los tests incluyen extracción/inyección W3C, parentesco, redacción, muestreo, errores y recepción OTLP/HTTP Protobuf real. Consulte VALIDATION.md para las pruebas ejecutadas y las que siguen pendientes.
