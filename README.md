# Decision Brain 0.9 — uso, operación y SDK

Sistema local de decisiones tipadas con fábrica de proyectos, evaluación, gateway, observabilidad y consumidor de eventos. Las acciones son propuestas: no ejecuta cambios en ERP, CRM ni tickets.

**Documentación única de uso:** [Guía completa](docs/GUIA_DE_USO.md) · [Versión HTML](docs/GUIA_DE_USO.html)

## Arranque

Requiere Python 3.12 o 3.13 y conexión durante la primera instalación. Extrae el proyecto en una carpeta nueva.

```bash
bash start.sh
```

Ejecuta las pruebas, entrena el ejemplo, evalúa y abre el informe. Para comercio y logística persistentes:

```bash
bash start.sh operate
```

Para conectar proyectos existentes en el primer arranque:

```bash
bash start.sh operate --projects-root "$HOME/Documents/2-lab-ai/decision_brain_factory/proyectos"
```

El panel se abre automáticamente. En otra terminal, desde la misma carpeta:

```bash
bash start.sh operate example --key caso-001
bash start.sh operate status
```

## SDK Python

El arranque instala también el SDK. Ejemplo contra el entorno persistente activo:

```bash
.venv/bin/python examples/sdk_predict.py --key sdk-caso-001
```

Para instalar solo el cliente en otra aplicación, sin las dependencias de entrenamiento:

```bash
python -m pip install ./sdk
```

No se requiere una publicación en PyPI. [Referencia del SDK](docs/SDK.md).

## Organización

| Carpeta | Contenido |
|---|---|
| `src/decision_brain/` | Entrenamiento, fábrica, gateway, observador y consumidor |
| `sdk/` | Paquete independiente `decision-brain-sdk` |
| `config/` | Contratos, presets, harness y políticas |
| `tests/` | Pruebas del sistema y SDK |
| `examples/` | Entradas y ejemplos ejecutables |
| `docs/` | Guía, referencia SDK y validación de esta entrega |
| `deploy/` | Plantillas de despliegue |
| `runs/`, `runtime/`, `proyectos/` | Datos generados al ejecutar; no vienen en el ZIP |

Esta entrega limpia la documentación anterior. Conserva código y capacidades previas. La documentación distingue desarrollo, promoción, decisiones por cerebro y estado del flujo completo: un cerebro verde no elimina una revisión pendiente de otro. Consulta [VALIDACION.md](docs/VALIDACION.md) para resultados y límites.
