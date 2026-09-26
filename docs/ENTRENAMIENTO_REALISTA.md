# Entrenamiento y evaluación de escenarios — versión 0.11

Esta ampliación corrige el generador del preset retail utilizado en preguntas_001. El motor de generación por factores se puede configurar para otros contratos; logística y manufactura conservan sus escenarios anteriores y no deben presentarse como validados por esta ampliación.

## Qué cambió

| Antes | Ahora |
| --- | --- |
| Tres frases de tarea por partición | Composición de frases reservadas por partición y orden variable |
| Cancelación implicaba prioridad y nivel alto | 18 combinaciones entre intención, urgencia explícita e impacto |
| Días desde compra podían servir de atajo | Misma distribución numérica para todas las etiquetas sintéticas |
| Faker cambiaba referencias alrededor de una frase fija | Referencias, productos, empresas y ciudades acompañan mensajes de negocio combinados |
| Harness de cuatro comprobaciones | 18 cruces de criterios, seis casos ambiguos y un rechazo de schema |
| Separación manual sin control de entidades | Preparación de CSV por grupo y rechazo de grupos compartidos |

Noul responde ahora si existe un plazo explícito de atención hoy o en las próximas horas. Score mide alcance del impacto operativo o económico. No son equivalentes a los criterios antiguos de prioridad y nivel de atención: las métricas anteriores y nuevas no son un experimento comparable de mejora de exactitud.

No se añadieron datos reales porque no se proporcionaron. Los escenarios siguen siendo sintéticos y sus combinaciones no cubren toda la distribución de un comercio real. No se utiliza un LLM ni una API externa para fabricarlos.

## Arranque completo

Extrae el proyecto en una carpeta nueva. Desde su raíz:

```bash
bash start.sh
```

Ejecuta pruebas de software, entrenamiento y harness. El informe de entrada es runs/latest.html. Si el harness falla, el proceso devuelve salida 1 y conserva los informes; eso es un rechazo de calidad del modelo, no un error de instalación. No rebajes min_pass_rate para ocultarlo.

## Entrenamiento explícito e informe del harness

```bash
bash start.sh demo --rows 2000 --trials 3 --epochs 40 --output runs/escenarios_011
bash start.sh harness --run runs/escenarios_011 --suite config/harness_suite.json --output runs/escenarios_011/evaluation
open runs/escenarios_011/report.html
open runs/escenarios_011/evaluation/report.html
```

El primer comando termina el entrenamiento y la prueba funcional; el segundo juzga las decisiones. Un directorio de salida debe ser nuevo. Los comandos open corresponden a macOS. El harness tiene expectativas fijadas en config/harness_suite.json; no entrena ni cambia el modelo.

## Interpretación del informe

| Sección | Qué permite comprobar |
| --- | --- |
| Diversidad | Cuántos textos de tarea distintos hay, excluyendo referencias Faker |
| Separación | Si se repiten textos exactos entre particiones |
| Combinaciones | Si existen cruces de etiquetas y asociación casi determinista entre cabezas |
| Ablación | Qué ocurre al anular el bloque de texto o el numérico del modelo ya entrenado |
| Curvas de pérdida | Si continúa mejorando validación o solo entrenamiento |
| Harness | Qué casos explícitos cumplen el contrato de decisión y cuáles fallan |

Una exactitud alta en plantillas sintéticas no demuestra comprensión general. La ablación mide sensibilidad a entradas; no es una explicación causal. Una pérdida de test menor que validación también puede deberse a diferencias de vocabulario y calibración.

## Incorporar datos reales etiquetados

El archivo examples/real_annotations_template.csv contiene solamente las cabeceras; no inventa registros reales. Añade casos autorizados, anonimizados y etiquetados por una persona competente. Para retail, sus columnas son:

```text
dias_desde_compra,mensaje,contexto,target__clasificacion,target__atencion_prioritaria,target__nivel,__group
```

Usa consulta/reclamacion/cancelacion para Choice, false/true para Noul y bajo/medio/alto para Score, conforme a las nuevas preguntas de config/brain.json. __group identifica de forma seudónima la entidad que no puede cruzar particiones: cliente, conversación o expediente. Todos los registros relacionados deben compartir ese identificador.

```bash
bash start.sh prepare-data --input data/reales_anotados.csv --output data/reales_particionados.csv --seed 42
bash start.sh --data data/reales_particionados.csv
```

prepare-data requiere al menos 200 filas y 20 grupos. Asigna grupos enteros a train/validation/calibration/test en proporciones aproximadas 55/15/15/15; las cantidades de filas pueden variar si los grupos tienen tamaños distintos. Valida al menos diez filas y todas las clases en cada partición. Si no se cumplen estas condiciones, falla sin publicar el archivo. No reintentes semillas hasta obtener métricas favorables; mejora la muestra y deja fijo el protocolo de evaluación.

Para una evaluación temporal, construye tú la columna __split según fechas y conserva __group; entrena directamente con ese CSV. La división aleatoria por grupos no simula cambios temporales. Revisa el harness con casos reales y versiona sus expectativas antes de evaluar. El harness incluido es una prueba sintética de regresión, no una certificación para los datos reales nuevos.

## Casos ambiguos y experimento de incertidumbre

El harness comprueba ausencia de intención, intenciones mezcladas, plazos e impactos contradictorios, contenido insuficiente y una consulta fuera del dominio. Espera revisión humana. El modelo puede fallar esas expectativas aun cuando acierte las clases de casos claros; los fallos permanecen visibles y bloquean un gate de promoción que exija aprobar la suite.

Se implementó exposición opcional a incertidumbre mediante etiquetas distribuidas: varias opciones plausibles comparten probabilidad; si falta una dimensión se usa una distribución uniforme. Se construye solamente con vocabulario de entrenamiento. Es una aproximación sintética, no una probabilidad humana observada.

La comparación ejecutada no justificó activarla: ambas variantes aprobaron 21/25 casos y la variante con exposición redujo la exactitud de Noul. Por eso synthetic_design.uncertainty_training_fraction queda en 0.0. Los experimentos pueden cambiarla hasta 0.5, pero alteran el contrato y requieren un entrenamiento nuevo. Esta exposición nunca se inyecta automáticamente en datos reales suministrados mediante train.

## Migración y límite operativo

El cambio de significado de las preguntas cambia el hash del contrato. No sustituyas brain.json dentro de una versión publicada. Genera un proyecto nuevo o prepara un release nuevo y evalúa su promoción. Los artefactos de 0.10 conservan su contrato original.

```bash
bash start.sh new --preset retail --brain-id comercio.escenarios --out proyectos/comercio_escenarios
cd proyectos/comercio_escenarios
bash start.sh
```

La fábrica, SDK, gates y observabilidad se conservan. Este trabajo mejora generación, evaluación e incorporación de datos, pero todavía no resuelve todos los casos ambiguos ni certifica operación productiva.
