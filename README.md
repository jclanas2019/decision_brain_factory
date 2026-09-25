# Decision Brain 0.5.0

## Arranque

Descomprime el ZIP en una carpeta nueva. Dentro de `decision_brain`, ejecuta:

```bash
bash start.sh
```

Requiere Python 3.12 (recomendado) o 3.13 y conexión para la primera instalación. Prepara el entorno, ejecuta las pruebas, entrena, evalúa y abre el informe. El acceso al último informe queda en `report.html`. Cada ejecución conserva sus propios resultados bajo `runs/`.

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
bash start.sh new --preset logistica --out proyectos/logistica
```

El proyecto generado conserva la misma estructura y se inicia entrando en su carpeta y ejecutando `bash start.sh`.

El contrato se edita en `config/brain.json` y los casos en `config/harness_suite.json`. El arranque acepta `--rows`, `--trials`, `--epochs` y `--data` para CSV anotado. Las rutas de entrada explícitas se interpretan desde la raíz del proyecto; las rutas declaradas en project.toml se resuelven desde ese archivo.

## Resultados y alcance

Salida 0: cumple los criterios. Salida 1: el modelo incumple casos del harness; el informe se conserva. Salida 2: fallo técnico. Pasar las pruebas del software no certifica las decisiones.

La demo usa datos sintéticos con Faker. El modelo local utiliza TF-IDF, variables numéricas y una red neuronal con salidas tipadas; no usa la API de JEV ni acredita equivalencia con su implementación. La búsqueda de configuraciones no es investigación autónoma. Consulta `docs/VALIDATION.md` para resultados de calidad y límites de verificación.
