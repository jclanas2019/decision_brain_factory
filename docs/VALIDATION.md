# Validación de la versión 0.8.0

Ejecutada en Linux con Python 3.12 el 25 de septiembre de 2026. Dependencias idénticas a 0.7; no se ejecutó macOS nativo.

| Verificación | Resultado |
| --- | --- |
| Suite Python | 85 pruebas aprobadas |
| Proyecto generado por la fábrica | 85 pruebas aprobadas |
| Flujo HTTP persistente | Comercio, logística, gateway, observador y consumidor en cinco procesos |
| Entrega automática | Evento logístico reconstruido y decidido por comercio |
| Reintento de caso | Misma decisión; sin nueva inferencia o traspaso |
| Caída del consumidor | Supervisor lo reinició automáticamente |
| Caída/reinicio del entorno | Evento fuente pendiente recuperado y entregado |
| Persistencia | Configuración, secretos y modelos reutilizados |
| Integridad del flujo probado | Dos casos, cuatro decisiones únicas |
| Trazas | Continuidad de trace_id y spans gate/predict/judge |
| Panel Web | Consumidor activo, entregas, filtro por cerebro y navegación a traza probados con DOM y HTTP real |
| Calidad visible | Comercio aprobado; logística fallida y roja |

Los tests del consumidor cubren cursor persistente, unicidad evento/ruta, recuperación, backoff máximo, versión y clave fijadas, cambio de ruta, ciclos y aislamiento del llamador. El gate valida handoff numérico, rango, campos exactos, rechazo de texto y su inclusión en la huella idempotente. Se probó generar y leer la definición launchd, sin secretos incorporados; no se ejecutó launchctl.

Durante la prueba se detectó que el sondeo de puertos recién cerrados podía fallar por TIME_WAIT. Se corrigió usando SO_REUSEADDR en el sondeo; el reinicio inmediato completo aprobó después de la corrección.

La prueba de interfaz usa JavaScript real con jsdom contra servicios locales reales. No es una inspección visual de Chromium/Safari ni certificación responsive. No se hicieron despliegue Docker, prueba de carga, failover entre hosts, corte eléctrico ni prueba nativa de launchd. SQLite y los locks son para un solo host.

Este entorno permanente usa DEVELOPMENT. No ejecuta acciones en ERP/CRM, no cambia políticas para aprobar modelos fallidos y no certifica calidad productiva. Las plantillas del traspaso interno requieren validación de negocio específica. La evidencia de esta versión está en docs/validation/operations-tests.log, operations-live.json y operations-live.log. Los demás archivos conservan antecedentes de entregas anteriores.
