# AutoEvals y autoresearch — versión 0.12

AutoEvals está integrado como dependencia real, fijada en 0.3.0. Se utilizan evaluadores locales: no se llama a un juez LLM, no se necesita API key ni se envían datos a Braintrust. Autoresearch es un ejecutor local de experimentos acotados, inspirado en la metodología de karpathy/autoresearch y adaptado al modelo NumPy de este proyecto. No se incluye ni ejecuta su entrenador GPU, ni se lanza automáticamente un agente que reescriba código.

## Un comando

Desde la raíz del proyecto extraído:

```bash
bash start.sh autoresearch
open runs/latest.html
```

El arranque habitual bash start.sh usa la misma integración: pruebas de software, investigación, entrenamiento final, AutoEvals y harness. No hace falta encadenar instalaciones o pruebas manuales. Usa --no-open si no quieres abrir el navegador.

Para datos reales ya particionados:

```bash
bash start.sh autoresearch --data data/reales_particionados.csv --trials 3 --epochs 40 --seed 42
```

La preparación por entidades se explica en ENTRENAMIENTO_REALISTA.html. Ninguna integración inventa evidencia real ni convierte datos sintéticos en datos de producción.

## Cómo se selecciona

| Etapa | Datos usados | Decisión |
| --- | --- | --- |
| Entrenamiento de cada candidato | train | Ajustar pesos |
| Selección y parada temprana | validation, mismas dos semillas por candidato | Mantener o descartar configuración |
| Calibración del seleccionado | calibration | Ajustar temperaturas |
| Evaluación final | test | Calcular métricas y AutoEvals; sin volver a la búsqueda |
| Harness | Suite fijada, con casos de negocio | Comprobar expectativas y regresiones si se proporciona baseline |
| Promoción | Política, evidencia y hashes del modelo | Autorizar o rechazar; nunca automática |

El modelo final utiliza la primera semilla fijada del candidato elegido; no se selecciona la semilla más favorable. El CSV completo se valida al cargarlo para detectar fugas entre grupos, pero la función de selección recibe solamente matrices de train y validation. El test final también se usa para recarga funcional y ablaciones, sin retroalimentar la selección.

## Qué aporta AutoEvals

| Evaluador | Procedencia | Lectura |
| --- | --- | --- |
| ExactMatch | AutoEvals | 1 si coincide la opción; 0 si no coincide |
| BrierQuality | Score propio usando AutoEvals Score | 1−Brier para Noul; 1−Brier/2 para multiclase |
| OrdinalCloseness | Score propio usando AutoEvals Score | 1−error absoluto/(número de niveles−1) |
| Aserciones del harness | ExactMatch y comprobaciones numéricas de rango | Acción, revisión y respuesta esperadas |

Todos los scores anteriores se interpretan de 0 a 1, mayor es mejor. Se conservan loss, Brier original, ECE, MAE, RMSE, matrices e interpretación. El gate de schema valida las distribuciones; la prueba funcional comprueba además las respuestas tipadas del modelo recargado.

AutoEvals aprobado significa que se cumplieron los umbrales numéricos configurados. No significa comprensión general, ausencia de errores ni que el harness esté aprobado.

## Presupuestos y aceptación

config/research_policy.json fija dos semillas por defecto, hasta 120 segundos por experimento y 600 segundos para el ciclo. El número solicitado de experimentos incluye la referencia y no puede superar el máximo de la política. El plazo se comprueba entre minibatches: es un límite cooperativo, no una interrupción del sistema operativo durante una operación NumPy.

Para conservar una propuesta debe reducir la pérdida media de validación al menos 0,0001 y no superar las tolerancias de regresión por cabeza, ExactMatch ni semilla, por defecto 0,02. Eso admite regresiones pequeñas dentro de la tolerancia: no equivale a cero cambios negativos caso por caso ni a significancia estadística. Las barras del gráfico representan desviación entre semillas, no intervalos de confianza.

Un candidato erróneo o fuera de tiempo se registra sin reemplazar el incumbente. Si falla la referencia, se detiene la ejecución. Las propuestas modifican únicamente anchura, tasa de aprendizaje y regularización. Los criterios, datos y código de evaluación no forman parte del espacio de búsqueda. Se registran hashes de configuración, política, datos, código y artefactos.

## Propuestas de un agente externo

El modo predeterminado propone cambios según la configuración y las curvas del incumbente. También admite hipótesis JSON preparadas por una persona o agente:

```bash
bash start.sh autoresearch --trials 3 --proposals config/research_proposals.example.json
```

La referencia siempre se ejecuta primero; por eso el JSON contiene dos propuestas para tres experimentos. El protocolo está en research/program.md. No existe ejecución arbitraria de shell o Python desde el JSON. No se incluye un agente LLM ni se afirma que esto sea RSI general. Reiniciar el comando crea una sesión nueva; no reanuda automáticamente un proceso interrumpido.

## Informes

| Ruta dentro de runs/session_... | Contenido |
| --- | --- |
| index.html | Estado de pruebas, AutoEvals y harness |
| model/report.html | Métricas, gráficos y decisiones de la búsqueda |
| model/autoevals.json | Scores de test por caso y pregunta |
| model/research/research.json | Hipótesis, configuración, semillas, pérdida y aceptación |
| model/research/results.tsv | Registro tabular keep/discard/error/timeout |
| evaluation/report.html | Expectativas del harness y casos fallidos |

El contrato y su hash se conservan dentro del modelo. Los informes contienen resultados y referencias sintéticas; al usar datos reales, aplica tu política de acceso y retención a los informes que incluyen estados de ejemplo.

## Promoción y compatibilidad

La política generada en config/promotion_policy.json exige AutoEvals, además del harness y los gates existentes. Se comprueba que los hashes de la evidencia correspondan al modelo. Un informe ausente o fallido bloquea promoción cuando require_autoevals=true. Las políticas antiguas no se reescriben automáticamente: deben adoptar esa propiedad y los umbrales autoevals para exigir esta evidencia.

Las nuevas sesiones mantienen salida 1 cuando falla AutoEvals o el harness y salida 2 cuando falla la ejecución o las pruebas del software. demo/train siguen siendo comandos de entrenamiento; para comprobar todos los gates con un único estado final, usa start.sh o start.sh autoresearch. La activación de versiones continúa siendo explícita.

El scaffolding incorpora estos módulos, políticas, pruebas y documentación. El SDK de inferencia conserva su instalación ligera; no depende de AutoEvals.

## Referencias

AutoEvals: https://github.com/braintrustdata/autoevals

Referencia de evaluadores: https://github.com/braintrustdata/autoevals/blob/main/SCORERS.md

Metodología autoresearch: https://github.com/karpathy/autoresearch

Se consultaron las fuentes oficiales y se ejecutó el paquete AutoEvals instalado. El código del ciclo local y research/program.md son implementaciones propias; no son copias del entrenador ni del programa de Karpathy.
