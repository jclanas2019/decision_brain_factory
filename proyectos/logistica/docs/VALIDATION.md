# Validación ejecutada: 0.6.0

Fecha: 25 de septiembre de 2026. Entorno: Linux, Python 3.12. Instalación limpia y aislada desde `bash start.sh --no-open`.

| Verificación | Resultado |
| --- | --- |
| Suite completa | 64 pruebas, 0 fallos, 0 errores |
| Proyecto nuevo generado por la fábrica | 64 pruebas aprobadas; gates, schemas y despliegue con identidad propia |
| Instalación desde entorno vacío | Completada, dependencias fijadas y paquete editable |
| Arranque por defecto | Entrenamiento, recarga funcional, HTML y harness completados |
| Harness retail del arranque | 4/4 casos aprobados; sin baseline |
| Calidad retail held-out | Loss media 0.290716; exactitud por cabeza 86.3%, 91.3%, 90.0% |
| Integración HTTP real | Dos workers con contratos diferentes, gateway y observador separados |
| Evento A → B | Estado reconstruido, traza compartida, solicitudes distintas |
| Reintento | Misma decisión y evento; una sola fila de auditoría |
| Versión errónea | 409 |
| Auditoría central | Sin texto de entrada, cadena de hashes y exportación sin duplicados |

Las pruebas cubren autenticación/ACL, schema, tipos, tamaños, JSON duplicado, TLS requerido, trazas, límites concurrentes, respuesta defectuosa, deriva del contrato, versión activa, carrera de cambio de versión, idempotencia concurrente/persistente y reservas pendientes. También cubren revisión por baja confianza, mapping de eventos, rechazo de promoción por harness fallido/regresión/huellas incorrectas y una promoción positiva con fixture técnico explícito. Ese fixture no certifica un modelo de negocio.

La demo logística de dos cerebros conserva un resultado de calidad 2/4 para cada modelo sintético. La interoperabilidad pasa; el harness de negocio falla y el observador lo marca rojo. Se usa development y no se promueve a producción. No se bajaron los umbrales para ocultar el resultado.

Las pruebas TOML conservan la normalización de rutas enlazadas que corrige `/var` frente a `/private/var`, y el arranque impone UTF-8. La ejecución nativa de macOS no se realizó. Tampoco se ejecutaron Docker, pruebas de carga sostenida, recuperación ante corte eléctrico ni auditoría de dependencias/pentest. Son verificaciones pendientes del despliegue.

La búsqueda de hiperparámetros no es investigación autónoma ni demuestra RSI general. El sistema es local, no llama a la API de Jev y no acredita equivalencia con su arquitectura privada. La evidencia sintética y cuatro casos de negocio no demuestran generalización industrial.

La evidencia de ejecución se incluye en `docs/validation/`: logs completos de las pruebas del proyecto base y del generado, arranque limpio y resultado JSON de integración. Los mensajes de error dentro de pruebas negativas son resultados esperados si la prueba termina en ok.
