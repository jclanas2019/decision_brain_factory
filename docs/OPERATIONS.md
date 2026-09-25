# Despliegue y operación

La infraestructura incluye un servicio de inferencia y un registro de versiones. La aprobación del modelo requiere datos reales y revisión del dominio. El registro de producción rechaza `synthetic_demo`; una declaración de procedencia no sustituye una auditoría de datos. La búsqueda automática jamás publica modelos por sí sola.

## 1. Instalar y probar

Use Python 3.12. Dentro del proyecto generado:

```bash
bash start.sh setup
.venv/bin/python -m unittest discover -s tests -v
```

La API expone `GET /health` (proceso vivo), `GET /ready` (modelo verificable), `GET /v1/model`, `POST /v1/predict` y `GET /metrics`. Las dos primeras rutas no requieren clave; las restantes requieren `Authorization: Bearer ...`. No hay endpoints para entrenamiento, publicación, ejecución de acciones o carga de archivos.

## 2. Ensayo local del servicio con datos sintéticos

```bash
./start.sh demo --rows 1000 --trials 3 --output runs/demo_service
.venv/bin/python -m decision_brain.releases --registry registry register --run runs/demo_service --version demo-v1 --environment development
.venv/bin/python -m decision_brain.releases --registry registry activate --version demo-v1 --environment development
mkdir -p secrets
(umask 077; .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))' > secrets/api_key)
export BRAIN_API_KEY_FILE="$PWD/secrets/api_key"
export BRAIN_MODE=development
bash scripts/serve.sh
```

En otra terminal, dentro del mismo proyecto:

```bash
export BRAIN_API_KEY_FILE="$PWD/secrets/api_key"
.venv/bin/python -m decision_brain.api_client --state examples/example_state.json
```

La respuesta incluye la versión del modelo, identificador de solicitud, decisiones, revisión requerida y acción propuesta. No ejecuta la acción. No publique datos sintéticos usando el modo de producción.

## 3. Preparar una versión de producción

Prepare un CSV real etiquetado con las cuatro particiones del contrato; separe organizaciones, autores o tiempo si corresponde. Entrene en una máquina administrativa, no en el contenedor de inferencia:

```bash
./start.sh train --data data/real.csv --trials 5 --epochs 60 --output runs/candidate_01
cp config/evidence.example.json evidence.json
```

Complete `evidence.json` con la huella del dataset de `report.json`, confirmación de datos reales, revisor, fecha, método de separación y justificación de aceptación del negocio. Defina umbrales por decisión en `config/promotion_policy.json`: los valores incluidos son ejemplos conservadores, no una norma válida para todas las industrias. La evaluación debe considerar costos de error, intervalos de confianza, grupos relevantes y un conjunto externo. Los controles automáticos revisan exactitud, pérdida, mejora frente a referencia, ECE, cobertura, acierto de casos automatizables, recall por clase y tamaño de prueba. El ECE por bins es un indicador, no prueba de calibración fuera de distribución.

```bash
.venv/bin/python -m decision_brain.releases --registry registry register --run runs/candidate_01 --version v1 --environment production --policy config/promotion_policy.json --evidence evidence.json
.venv/bin/python -m decision_brain.releases --registry registry activate --version v1 --environment production
```

Si la promoción es rechazada, el servicio no tiene una nueva versión. Revise los motivos; no cambie procedencia o umbrales solo para hacer pasar una prueba sintética.

## 4. Contenedor

Cree `secrets/api_key` como en el ensayo y haga que el secreto pueda ser leído por el UID 10001 del contenedor sin hacerlo público. Según el sistema anfitrión, use un gestor de secretos o ajuste propietario/grupo. El registro debe ser legible por el UID 10001 y escribible únicamente por el operador administrativo.

```bash
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
curl --fail http://127.0.0.1:8000/ready
```

Compose usa modo `production`, usuario sin privilegios, sistema de archivos de solo lectura, registro de modelos montado de solo lectura, límites de CPU/memoria y puerto ligado a localhost. Para acceso remoto, coloque un proxy TLS autenticado delante y mantenga el backend en una red privada. La clave no viaja cifrada si expone HTTP directamente. No incluya secretos ni datasets en la imagen.

## Versiones y rollback

La versión registrada es inmutable para el CLI. Se verifican hashes antes de cargarla. Las huellas detectan cambios, pero no sustituyen permisos: un administrador con acceso de escritura al registro puede modificar el manifiesto. Solo un pipeline confiable debe poder escribirlo. El servicio lee un puntero actualizado atómicamente y recarga al recibir una nueva solicitud. Una petición ya iniciada termina con su versión original, devuelta en la respuesta.

```bash
.venv/bin/python -m decision_brain.releases --registry registry activate --version v2 --environment production
.venv/bin/python -m decision_brain.releases --registry registry rollback --environment production
```

`registry/audit.jsonl` conserva los cambios de activación. Respalde el registro y sus manifiestos; pruebe restauración y rollback en su infraestructura antes de abrir tráfico. Rotar la clave exige actualizar el secreto y reiniciar el servicio. La API acepta una clave compartida por instancia; para usuarios/tenants independientes utilice una pasarela con identidad y cuotas propias.

## Observabilidad y límites

Los logs JSON de inferencia contienen identificador, versión, tiempo/estado y necesidad de revisión. No guardan contexto, predicciones completas ni claves. Envíelos a su colector con política de retención. `/metrics` expone contadores de solicitudes, rechazos, predicciones y revisiones. Vigile tasa de revisión, errores, latencia y calidad con etiquetas posteriores. No se implementa detección automática de drift ni reentrenamiento automático.

El límite de peticiones es por proceso, no distribuido; el despliegue usa un worker. Si replica instancias, aplique una cuota global en el proxy. Hay límite de 64 KiB por cuerpo, 12.000 caracteres por campo de texto, magnitud numérica máxima de 1e12 y cuatro inferencias concurrentes. El servidor además limita conexiones y espera del cuerpo. El timeout de entrada no cancela un cálculo numérico ya iniciado; los límites de recursos del contenedor y la cota del modelo son necesarios. Ajuste límites tras una prueba de carga real.

## Verificación y límites de esta entrega

Las pruebas de integración ejercitan el servidor ASGI con autenticación, esquemas, límites, hashes, cambios de versión y rechazo de producción sintética. No reemplazan pentest, pruebas de carga de su hardware ni revisión de calidad por industria. El workflow CI incluido ejecuta las pruebas y la demo en Linux y macOS con Python 3.12 y 3.13 cuando se sube a un repositorio. La construcción Docker y la auditoría de dependencias deben ejecutarse antes de un despliegue. Revise resultados del escaneo y actualice dependencias antes de publicar; un pin no garantiza ausencia de vulnerabilidades.

No se desplegó esta aplicación en infraestructura externa. En el entorno de desarrollo no hay Docker disponible, por lo que el build/arranque del contenedor queda como validación necesaria en su máquina o CI.
