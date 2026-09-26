# Protocolo local de autoresearch — Decision Brain

Objetivo: reducir la pérdida de validación del cerebro manteniendo los criterios de calidad fijados. Este protocolo se inspira en el ciclo público de experimentos de karpathy/autoresearch; estas instrucciones y el ejecutor son propios de Decision Brain.

El primer experimento establece la referencia. Cada propuesta describe una hipótesis verificable y cambia únicamente hidden, lr o decay dentro de los límites que valida el ejecutor. El presupuesto, las semillas y las tolerancias se fijan antes de empezar.

No modifiques la suite, las etiquetas, la partición test, el evaluador, los umbrales de promoción o las reglas de routing para favorecer un candidato. No consultes resultados finales de test para proponer la siguiente configuración. La investigación utiliza únicamente train y validation; calibration se utiliza después de seleccionar, y test queda para evaluación final.

Para proponer desde un agente externo, escribe una lista JSON con exactamente trials−1 propuestas, siguiendo config/research_proposals.example.json. Ejecuta bash start.sh autoresearch --proposals RUTA --trials N. Solo se leen datos JSON: no se ejecutan comandos ni código provenientes de propuestas. El modo por defecto genera propuestas locales según el resultado y la brecha de pérdida del incumbente.

Lee model/research/research.json y results.tsv para conocer hipótesis, semillas, pérdidas y motivos keep/discard/error/timeout. Keep significa mantener una configuración para la búsqueda, no desplegarla. Cada configuración usa las mismas semillas; no elijas la semilla de mejor resultado como artefacto final.

El agente no se inicia automáticamente y este ejecutor no modifica su propio código. Para cambiar la arquitectura fuera del espacio admitido, abre una revisión de software separada y valida nuevamente sus pruebas. No se promete investigación autónoma general.

Una evaluación AutoEvals aprobada no sustituye el harness, datos reales ni aceptación de negocio. Nunca actives una versión con un gate fallido. Si un candidato falla o excede el presupuesto, registra la causa y conserva el incumbente. Si falla la referencia, detén la ejecución.
