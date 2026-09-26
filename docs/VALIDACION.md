# Validación 0.12: AutoEvals y autoresearch

Se ejecutaron 123 pruebas de software sin fallos. La dependencia real AutoEvals 0.3.0 está instalada y su evaluación local se probó bloqueando conexiones de red. pip check no detectó incompatibilidades.

El entrenamiento de evidencia usó 2.000 filas sintéticas, tres experimentos y dos semillas por experimento. La referencia se conservó; las dos propuestas se descartaron. El registro durable coincide con la búsqueda incluida en report.json. AutoEvals y la recarga funcional pasaron; el harness aprobó 21/25 casos y permanece FAIL. No se activó ninguna versión ni se relajaron expectativas.

| Control | Resultado |
| --- | --- |
| AutoEvals sobre test | PASS |
| Recarga y respuesta tipada, 300 casos | PASS |
| Propuestas mejoradas aceptadas | 0; se conserva baseline |
| Harness | FAIL: 21/25 |
| Promoción | Bloqueada por harness y datos sintéticos |

Los tests verifican propuesta fuera de límites, regresión por cabeza/semilla/ExactMatch, presupuesto temporal, conservación del incumbente ante error, checkpoint final, falta de evidencia AutoEvals, hashes de otro modelo y propagación de FAIL al arranque. No se ejecutó macOS nativo, una carga productiva ni un agente externo.

Evidencia actual: evidencia/entrenamiento_012/report.html, evidencia/entrenamiento_012/research/research.json, evidencia/harness_012/report.html, evidencia/resumen_012.json y evidencia/pruebas_012.log. Los números de versiones anteriores se conservan como histórico, no como validación de 0.12.

## Evidencia anterior

# Validación 0.11: escenarios y datos

Se ejecutaron 111 pruebas de software sin fallos. Se entrenó el preset retail con 2.000 registros sintéticos y tres candidatos; 300 registros se reservaron para test. La recarga y el gate de respuestas tipadas pasaron en los 300 casos.

El harness ampliado NO aprobó: 21/25 casos. Fallan intenciones_mixtas, impacto_contradictorio, mensaje_vacio_semantico y fuera_dominio. Una política que exija aprobar el harness no debe promocionar este modelo. El comando de harness devuelve 1 por calidad, conservando sus informes.

| Medida | Resultado |
| --- | --- |
| Textos de entrenamiento distintos | 1.084 de 1.100 |
| Combinaciones de etiquetas | 18 en cada partición |
| Textos exactos compartidos entre particiones | 0 |
| Exactitud Choice / Noul / Score por nivel | 100 % / 99,3 % / 100 % |
| Exactitud sin texto | 34 % / 50 % / 35,3 % |
| Loss de test media | 0,06970 |
| MAE de Score | 0,01732 niveles |

Estos resultados altos corresponden a frases sintéticas combinadas y se deben leer junto a los cuatro fallos del harness. No hay validación sobre casos reales ni sobre macOS nativo. Cambió la semántica de las preguntas: no es válido comparar estas exactitudes con las de 0.10 como si fueran el mismo problema.

El experimento opcional con etiquetas distribuidas de incertidumbre tampoco superó 21/25 casos y redujo Noul a 95,7 %. Se entrega desactivado por defecto; no fue promovido por parecer más sofisticado.

La evidencia actual está en docs/evidencia/entrenamiento_011, harness_011, experimento_incertidumbre_011 y resumen_011.json. Las carpetas con sufijo 010 corresponden a la versión anterior.

## Evidencia anterior

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
