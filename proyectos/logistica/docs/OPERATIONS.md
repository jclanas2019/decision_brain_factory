# Operación y promoción 0.6

## Arranque local

```bash
bash start.sh
bash start.sh gates-demo
```

El primero ejecuta pruebas, entrenamiento, prueba funcional de recarga, harness e informe HTML. El segundo prueba el sistema de gates con cuatro procesos HTTP separados y cierra los procesos al terminar. No requiere configurar secretos ni producción. Para repetir solo las pruebas: `bash start.sh check`.

## Promoción administrativa

Un modelo sintético no puede registrarse en producción. Prepare datos reales etiquetados con las particiones del contrato y separación por tiempo, organización o autor según el problema. Revise los costos de error, representatividad y umbrales de `config/promotion_policy.json` con el responsable del dominio.

```bash
bash start.sh train --data data/real.csv --trials 5 --epochs 60 --output runs/candidate_01
bash start.sh harness --run runs/candidate_01 --baseline runs/baseline_aprobado \
  --suite config/harness_suite.json --output runs/candidate_01_harness
cp config/evidence.example.json evidence.json
```

Si el harness devuelve 1, detenga la promoción y conserve los informes. Si devuelve 2, corrija el fallo técnico. Complete evidence.json con la huella del dataset del informe de entrenamiento, datos reales confirmados, revisor, fecha, separación y aceptación de negocio. `harness_sha256` debe ser la huella SHA256 exacta de `runs/candidate_01_harness/report.json`. Puede calcularla sin herramientas externas:

```bash
.venv/bin/python -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("runs/candidate_01_harness/report.json").read_bytes()).hexdigest())'
```

El campo `suite_sha256` del reporte debe estar autorizado en `harness.approved_suite_sha256` de la política después de revisar la suite. La lista viene vacía: no se aprueba automáticamente cualquier prueba. La política exige comparación contra baseline. Para la primera versión, un responsable puede aprobar explícitamente `require_baseline: false` y documentar la excepción; no declare que hubo comparación si no existe.

```bash
.venv/bin/python -m decision_brain.releases --registry registry/production register \
  --run runs/candidate_01 --version v1 --environment production \
  --harness runs/candidate_01_harness/report.json \
  --policy config/promotion_policy.json --evidence evidence.json
.venv/bin/python -m decision_brain.releases --registry registry/production activate \
  --version v1 --environment production
```

El registro vincula el harness a los cuatro artefactos exactos del modelo y la suite autorizada. Exige casos consistentes, umbral, cero regresiones, procedencia y métricas de calidad. Activación y lectura verifican nuevamente la evidencia almacenada y las huellas. No basta editar `passed: true`. Los administradores que pueden reescribir política, evidencia y manifiestos siguen siendo una autoridad de confianza; no hay firma externa de attestations.

Los cambios de activación quedan en `registry/production/audit.jsonl`; las decisiones del gateway quedan en `registry/audit.jsonl`. Son registros distintos.

```bash
.venv/bin/python -m decision_brain.releases --registry registry/production rollback --environment production
```

Rollback verifica la versión previa. El semáforo recomienda esta operación cuando corresponde, pero no la ejecuta automáticamente.

## Procesos locales permanentes

Para cada worker configure BRAIN_ID, BRAIN_REGISTRY, BRAIN_MODE y BRAIN_API_KEY. `scripts/serve.sh` deriva el ID del contrato de gate y usa production por defecto. El secreto BRAIN_API_KEY debe coincidir con el nombre indicado por upstream_token_env en el catálogo del gateway, por ejemplo BRAIN_RETAIL_TRIAJE_TOKEN. Son secretos internos distintos de los secretos de llamadores.

En el gateway configure BRAIN_ORCHESTRATOR_TOKEN, BRAIN_POSTVENTA_TOKEN y los secretos de todos sus workers. Cada secreto debe tener al menos 32 caracteres; genere valores aleatorios independientes y consérvelos en su gestor de secretos. No los escriba en git. El observador usa su propio BRAIN_OBSERVER_TOKEN. Reinicie el proceso correspondiente al rotar secretos.

```bash
# Terminal del worker, con las variables indicadas configuradas:
bash scripts/serve.sh
# Terminal del gateway:
export BRAIN_TLS_CERT=/ruta/cert.pem BRAIN_TLS_KEY=/ruta/key.pem
bash start.sh gateway
# Terminal del observador:
bash start.sh observer
```

El gateway de producción termina TLS. Los clientes deben confiar en su certificado; no deshabilite verificación TLS. Los workers permanecen privados. Mantenga el observador ligado a localhost o detrás de una red administrativa cifrada. El gateway autoriza por llamador y cerebro; no implementa OAuth, aislamiento multitenant de datos ni cuotas distribuidas.

## Compose

La plantilla incluye un worker, un gateway global TLS y un observador separado. Requiere versión productiva previamente activada, secretos y certificados; no entrena durante el arranque.

Configure cuatro variables independientes: BRAIN_STACK_WORKER_TOKEN, BRAIN_ORCHESTRATOR_TOKEN, BRAIN_POSTVENTA_TOKEN y BRAIN_OBSERVER_TOKEN. Coloque certificado/cadena y clave en `secrets/tls/cert.pem` y `secrets/tls/key.pem`. El UID 10001 debe leerlos y escribir el directorio central registry para SQLite y auditoría; los modelos production se montan de solo lectura. Ajuste propietario/grupo sin hacer públicos los secretos.

```bash
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
curl --fail --cacert secrets/tls/cert.pem https://localhost:8443/ready
curl --fail http://localhost:9100/ready
```

Use un certificado cuyo nombre corresponda al hostname. El worker no publica puerto al anfitrión. Para añadir cerebros, añada workers privados y entradas al catálogo compartido; mantenga un solo gateway y un observador. La plantilla de un solo worker no crea automáticamente una topología multiworker.

## Límites operativos

SQLite, idempotencia y locks de archivos están diseñados para un host con almacenamiento local. No despliegue varias réplicas con bases independientes esperando idempotencia global; tampoco use WAL sobre un filesystem de red. A mayor volumen, migre el almacenamiento/outbox y las métricas a servicios apropiados, conservando los contratos y pruebas. El exportador verifica la cadena de auditoría completa: requiere archivo administrado y pruebas de rendimiento con el volumen esperado.

Los timeouts de red no cancelan necesariamente un cálculo ya iniciado. Las reservas pendientes no se reciclan automáticamente. Configure recursos y pruebe carga, fallos, respaldo/restauración y rotación en su infraestructura. La auditoría protege frente a cambios accidentales y a través de la API; no protege contra un administrador malicioso del disco. No se implementa reentrenamiento automático ni detección estadística de drift.

Docker, macOS nativo y carga de producción no fueron ejecutados en esta entrega. La configuración está incluida, pero requiere esas verificaciones antes de abrir tráfico real. El workflow CI de Linux/macOS no equivale a resultados ejecutados.
