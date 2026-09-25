# Decision Brain 0.8.0

## Comercio y logística como entorno persistente

```bash
bash start.sh operate
```

Crea los proyectos que falten, reutiliza modelos ya entrenados, evalúa el harness y arranca dos cerebros, gateway, observador y consumidor automático. Abre el panel en http://127.0.0.1:8104. Los datos permanecen en `runtime/commerce-logistics/`. Ctrl+C detiene los procesos; repetir el comando reutiliza datos, modelos, secretos y eventos pendientes.

Para conectar los proyectos que ya tienes en otra carpeta, en el primer arranque:

```bash
bash start.sh operate --projects-root "/ruta/decision_brain_factory/proyectos"
```

Esa carpeta debe contener `comercio` y `logistica`. Se validan los contratos; no se reemplazan sus fuentes ni sus configuraciones. Si un proyecto no tiene modelo entrenado, se genera una versión sintética de desarrollo y se evalúa. Este entorno es DEVELOPMENT: no convierte modelos fallidos en versiones productivas.

En otra terminal, desde esta misma carpeta:

```bash
bash start.sh operate example --key caso-ejemplo-001
bash start.sh operate status
```

El ejemplo usa datos ficticios y compra hace siete días; repetir la misma clave devuelve la misma decisión. El consumidor reconstruye el estado de comercio y realiza el segundo paso automáticamente. El panel muestra los traspasos y su estado. [Guía completa y arranque automático en macOS](docs/PERSISTENT_OPERATIONS.md).

## Arranque

Descomprime el ZIP en una carpeta nueva. Dentro de `decision_brain_operations`, ejecuta:

```bash
bash start.sh
```

Requiere Python 3.12 (recomendado) o 3.13 y conexión para la primera instalación. Prepara el entorno, ejecuta las pruebas, entrena, evalúa y abre el informe. El acceso al último informe queda en `report.html`. Cada ejecución conserva sus propios resultados bajo `runs/`.

## Panel web de observabilidad

```bash
bash start.sh observe-demo
```

Prepara dos microcerebros de desarrollo, un gateway y un observador. Abre el panel web con autenticación temporal y mantiene los cuatro procesos funcionando hasta Ctrl+C. La dirección se imprime en la terminal. No requiere Docker, Node ni un colector externo. Incluye estado y calidad por cerebro, gráficos de tráfico, latencias, decisiones y trazas OpenTelemetry gate → predict → judge.

Para un entorno ya configurado: `bash start.sh observer`, con BRAIN_OBSERVER_TOKEN definido, sirve el panel en http://127.0.0.1:9100. Introduce ese token en la pantalla de acceso. El observador usa su catálogo y registro; no descubre automáticamente proyectos dispersos.

[Guía de observabilidad, OpenTelemetry y exportación OTLP](docs/OBSERVABILITY.md).

## Organización

| Ruta | Contenido |
| --- | --- |
| `src/decision_brain/` | Paquete Python: entrenamiento, inferencia, harness, servicio y fábrica |
| `tests/` | Pruebas automatizadas |
| `config/` | Contrato, suite, presets, políticas y dependencias fijadas |
| `examples/` | Ejemplo de contexto de entrada |
| `scripts/` | Preparación del entorno y scripts auxiliares |
| `docs/` | Operación, harness, TOML y validación |
| `deploy/` | Dockerfile y Compose |
| `.github/workflows/` | Integración continua |
| `runs/` | Resultados generados al ejecutar; no se incluyen en el ZIP |

En la raíz sólo están `start.sh`, este README, `pyproject.toml` y `project.toml`, además de los archivos de exclusión de Git/Docker. `pyproject.toml` instala el paquete con distribución src; `project.toml` configura el harness.

## Comandos

Todos se ejecutan desde la raíz:

```bash
bash start.sh check
bash start.sh --no-open
bash start.sh harness
bash start.sh predict --state examples/example_state.json
bash start.sh list
bash start.sh gates-demo
bash start.sh new --preset logistica --brain-id logistica.incidencia --out proyectos/logistica
```

El proyecto generado conserva la misma estructura y se inicia entrando en su carpeta y ejecutando `bash start.sh`.

El contrato se edita en `config/brain.json` y los casos en `config/harness_suite.json`. El arranque acepta `--rows`, `--trials`, `--epochs` y `--data` para CSV anotado. Las rutas de entrada explícitas se interpretan desde la raíz del proyecto; las rutas declaradas en project.toml se resuelven desde ese archivo.

## Resultados y alcance

Salida 0: cumple los criterios. Salida 1: el modelo incumple casos del harness; el informe se conserva. Salida 2: fallo técnico. Pasar las pruebas del software no certifica las decisiones.

La demo usa datos sintéticos con Faker. El modelo local utiliza TF-IDF, variables numéricas y una red neuronal con salidas tipadas; no usa la API de JEV ni acredita equivalencia con su implementación. La búsqueda de configuraciones no es investigación autónoma. Consulta `docs/VALIDATION.md` para resultados de calidad y límites de verificación.

## Gates incluidos de serie

`bash start.sh gates-demo` ejecuta dos microcerebros con contratos diferentes, un gateway y un observador como cuatro procesos HTTP locales. Comprueba reintentos idempotentes, trazas, reconstrucción del estado desde eventos, rechazo de versión y auditoría central. Abre un HTML con resultados e interpretación. Los secretos son efímeros; los procesos se cierran al terminar.

| Componente | Responsabilidad |
| --- | --- |
| `decision_brain.gateway` | Identidad y permisos, catálogo, contratos, versión activa, idempotencia, respuesta tipada |
| `decision_brain.observer` | Auditoría central sin texto de entrada, métricas, consultas y semáforo operativo |
| `decision_brain.releases` | Evidencia offline, harness aprobado, ausencia de regresiones, promoción y rollback |
| `decision_brain.router` | Enrutamiento determinista de eventos por catálogo y reglas declaradas |
| Fábrica | Genera lo anterior, JSON Schema, `config/gates/` y despliegue por proyecto |

Consulta [docs/GATES.md](docs/GATES.md) para contratos, comandos y configuración. [docs/OPERATIONS.md](docs/OPERATIONS.md) describe promoción y despliegue. La configuración de producción se cierra ante falta de evidencia; la demo funciona en desarrollo y no promueve modelos sintéticos.
