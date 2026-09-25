# Operación persistente · 0.8.0

## Arranque único

```bash
bash start.sh operate
```

La primera ejecución prepara comercio y logística en proyectos/ si faltan. Si ya existen, verifica sus campos y reutiliza el modelo señalado por runs/latest_model.json. Si no hay modelo, entrena una versión sintética y ejecuta el harness; no afirma que esos datos sean productivos. Se registra una copia inmutable de cada modelo en un registry development propio del entorno, sin cambiar el registro de producción de los proyectos.

En ejecuciones posteriores se conserva la configuración inicial, versiones activas, claves, cola, auditoría y trazas. No se reentrena ni se elige silenciosamente el último candidato. El usuario decide cuándo evaluar y activar una nueva versión. No mezcle carpetas de ZIP distintos ni copie un entorno .venv antiguo: extraiga la entrega completa en una carpeta nueva.

Para conectar tus carpetas existentes:

```bash
bash start.sh operate --projects-root "$HOME/Documents/2-lab-ai/decision_brain_factory/proyectos"
```

También admite --commerce y --logistics con rutas individuales. --projects-root exige las dos carpetas y sus contratos; una ruta equivocada no crea proyectos sustitutos. Volver a indicar las mismas rutas es válido; usar otras requiere otro --state. El estado guarda rutas absolutas: mover proyectos o todo el entorno requiere reconfigurar rutas deliberadamente.

Puertos por defecto: comercio 8101, logística 8102, gateway 8103, panel 8104. --base-port cambia el primer puerto al crear un entorno. Los cuatro deben estar libres. El comando abre el panel con una URL privada que contiene el token en un fragmento; la UI lo elimina de la barra y lo mantiene solo en memoria. No compartas esa URL. El consumidor es un quinto proceso sin puerto HTTP.

## Uso del flujo

En otra terminal:

```bash
bash start.sh operate example --key caso-ejemplo-001
bash start.sh operate status
```

El comando example usa una escena ficticia del preset logístico y compra hace siete días. Permite comprobar el flujo, no medir calidad de clientes reales. El gateway devuelve la decisión inicial; la segunda llega de forma asíncrona. Consulta Traspasos entre cerebros en el panel. Repetir la misma clave devuelve la misma decisión inicial y no genera otro traspaso.

Para tus propios casos crea un JSON y usa submit:

```json
{
  "brain_id": "logistica.incidencia",
  "context": {
    "horas_desviacion": 48,
    "estado_entrega": "La entrega sigue pendiente dos días después de la fecha acordada.",
    "contexto": "Seguimiento interno de un pedido de comercio."
  },
  "handoff": {"dias_desde_compra": 7}
}
```

```bash
bash start.sh operate submit --file caso.json --key pedido-123-evaluacion-1
```

handoff es un contrato auxiliar numérico declarado en el gate del entorno. El dato de compra debe proceder del sistema de negocio: no se infiere a partir del retraso. Exige campos exactos, números finitos no negativos, límites de tamaño y magnitud, sin texto personal ni campos extra. Se valida antes de inferir y forma parte de la huella de idempotencia. Los nuevos schemas se encuentran en runtime/commerce-logistics/logistica/edge/config/gates/.

El modelo logístico solo recibe su context original. El evento incluye el hecho numérico validado. Comercio recibe sus propios campos: edad real de la compra, una descripción declarada de la hipótesis logística y contexto de traspaso interno. No se fabrican frases atribuidas al cliente ni intención de cancelar. Estas plantillas son configuración del negocio: requieren evaluación específica antes de usarse en producción. La cadena propone decisiones; no envía mensajes ni crea tickets.

Para una decisión independiente de comercio, submit acepta un envelope con brain_id comercio.triaje y su context, sin handoff. Ese evento no tiene ruta de retorno y no genera un ciclo.

## Persistencia y entrega automática

El consumidor lee el outbox central. En una transacción descubre eventos nuevos, crea entregas únicas por evento/ruta y avanza el cursor. Solo consume eventos del llamador orchestrator. Cada entrega conserva versión destino, hash de la regla e Idempotency-Key estable. Se envía únicamente al gateway, que reconstruye y valida el estado destino. El gateway también comprueba el hash de ruta de la entrega; un cambio pendiente requiere revisión.

Si el consumidor cae después de la respuesta HTTP pero antes de guardar el resultado, repite con la misma clave; el gateway devuelve la decisión ya guardada. Las reservas ambiguas del gateway no se borran ni se reejecutan automáticamente. La garantía es una inferencia como máximo por clave en este host, no exactly-once de acciones externas.

Errores transitorios tienen backoff y un máximo de cinco intentos. Errores de contrato, identidad, versión, ruta o respuesta inválida pasan a revisión. La tabla deliveries permanece en el mismo SQLite que el outbox. El panel muestra pendientes, entregadas y requiere revisión, intento, resultado y última señal del consumidor. Muestra las últimas 100 entregas. No incluye un botón de reenvío inseguro: tras corregir una incidencia, un operador debe reconciliar la entrega y la reserva original antes de autorizar otra decisión. No edites SQLite mientras los servicios estén funcionando.

La configuración de rutas se valida para evitar ciclos; hay un solo consumidor por base, protegido con un lock de proceso. El supervisor reinicia servicios caídos hasta tres veces en 60 segundos; después detiene el entorno y conserva los logs. Al arrancar de nuevo el outbox permite recuperar eventos pendientes. No hay promesa de alta disponibilidad: un único host sigue siendo un punto de fallo.

## Calidad y cambios de modelo

El panel conserva los resultados originales del harness. Logística sigue pudiendo aparecer roja mientras comercio está verde; no se rebajan umbrales para permitir la cadena de desarrollo. No se promociona ningún modelo automáticamente.

Los modelos activos están en runtime/commerce-logistics/comercio/registry y logistica/registry. Para evaluar candidatos, usa entrenamiento y harness con baseline, y el CLI releases para registrar una versión nueva. Producción requiere evidencia real y la política de promoción ya incluida; el comando operate de esta entrega no levanta una flota production. Una entrega pendiente sigue fijada a su versión original y falla de forma visible si se cambia la versión activa.

## Mantenerlo activo tras cerrar la terminal en macOS

Primero inicia el entorno una vez y detenlo con Ctrl+C. Genera una definición launchd con rutas de esta instalación:

```bash
bash start.sh operate service-file
launchctl bootstrap "gui/$(id -u)" "$PWD/runtime/commerce-logistics/decision-brain.plist"
```

Para detener ese servicio:

```bash
launchctl bootout "gui/$(id -u)" "$PWD/runtime/commerce-logistics/decision-brain.plist"
```

El proceso permanece activo tras cerrar la terminal. Para cargarlo automáticamente en futuros inicios de sesión, copia la definición a ~/Library/LaunchAgents con el mismo nombre único indicado por Label; no se instala ni modifica launchd automáticamente desde el proyecto. KeepAlive reinicia el supervisor y ThrottleInterval limita reinicios. No ejecutes simultáneamente el comando foreground y launchd para el mismo estado. La definición se genera, pero no se probó nativamente en macOS.

El archivo de secretos se crea con permisos 0600 y el directorio de estado con 0700. La definición launchd no contiene claves. Logs del supervisor: supervisor.stdout.log y supervisor.stderr.log; registros por proceso: comercio.log, logistica.log, gateway.log, observer.log y consumer.log. Aplica retención y backups adecuados. Ningún puerto se publica fuera de localhost; para acceso remoto hacen falta TLS y controles administrativos.
