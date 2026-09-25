# Validación de la ampliación 0.10 — Choice, Score y Noul

Se ejecutaron 106 pruebas, sin fallos ni errores, en el proyecto principal y otras 106 en un proyecto generado por la fábrica. Incluyen entrenamiento y recarga con los tres tipos, semántica numérica, compatibilidad boolean, rechazo de respuestas alteradas, SDK y rangos de harness.

La ejecución adicional utilizó 2.000 filas sintéticas, tres candidatos y hasta 40 épocas con parada temprana. Su test separado contiene 300 filas. La prueba funcional verifica recarga y validación de todas las respuestas tipadas. El harness existente aprobó sus cuatro casos; no se comparó contra una versión de referencia.

| Cabeza | Loss de test | Resultado adicional |
| --- | --- | --- |
| Choice | 0,35613 | Exactitud: 86,3 % |
| Noul | 0,19374 | Brier binario: 0,06130 |
| Score | 0,32228 | MAE: 0,23520 niveles |

El test_loss medio fue 0,290716. La separación entre pérdida de entrenamiento y validación muestra sobreajuste; estos datos sintéticos y cuatro casos de harness no certifican calidad de producción. No se modificaron los umbrales del harness para obtener el resultado.

Evidencia: evidencia/pruebas_primitivas_010.log, evidencia/pruebas_scaffolding_010.log, evidencia/entrenamiento_primitivas_010.log, evidencia/entrenamiento_010/report.html y evidencia/harness_010/report.html. Se comprobaron las referencias locales de los HTML y las leyendas del gráfico de pérdida. No se ejecutó macOS nativo ni una prueba de carga.

## Evidencia anterior de la versión 0.9

# Validación de la versión 0.9

Ejecución en Linux/Python 3.12. La documentación se consolidó: README de entrada, GUIA_DE_USO en Markdown/HTML, referencia SDK y este registro. Se retiraron manuales duplicados y logs históricos de otras versiones del paquete entregado.

| Verificación | Resultado |
|---|---|
| Suite completa | 95 pruebas aprobadas |
| Proyecto generado por la fábrica | 95 pruebas aprobadas |
| SDK instalado desde wheel en un entorno aislado | 10 pruebas del SDK aprobadas; sin numpy ni paquete del servidor |
| Instalación editable del sistema completo | Imports del servidor y del SDK correctos |
| Integración HTTP real | Catálogo, predicción tipada, replay idempotente, consumidor automático, consulta de decisiones, trazas y métricas aprobados |
| Documentación | Sintaxis de ejemplos Python/JSON, estructura HTML e índice comprobados |

Las diez pruebas del SDK están incluidas en las 95 del sistema; se repitieron además contra la distribución instalada de forma independiente. No son 105 pruebas distintas.

El cliente no reintenta automáticamente, no ejecuta acciones y no modifica modelos. La versión y el cuerpo quedan fijados en PreparedDecision. Se prueban timeout, códigos HTTP, protección de mensajes de error, respuesta probabilística inválida, replay, filtros y propagación de traza.

La compatibilidad mínima declarada del SDK es Python 3.10, pero solo se ejecutó con Python 3.12 en este entorno. No se ejecutó una matriz completa de Python, macOS nativo, Docker o carga productiva. El HTML se verificó estructuralmente; no se certifica su renderizado en todos los navegadores.

Esta entrega no corrige la calidad insuficiente del modelo logístico ni añade expediente global/revisión humana resolutiva. La guía documenta esas limitaciones. Los resultados de validación actuales están en docs/evidencia/.
