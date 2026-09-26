# Choice, Score y Noul — Decision Brain 0.10

Esta versión entrena y devuelve tres tipos de preguntas locales. No llama a TypeSafe ni reproduce los pesos, arquitectura privada o fórmula de confianza de Jev. Cada pregunta es una cabeza supervisada: se fija en el contrato antes de entrenar; no acepta preguntas nuevas durante una predicción.

| Tipo | Objetivo | Resultado principal | Evaluación |
| --- | --- | --- | --- |
| Choice | Elegir una opción del catálogo | choice, probabilities, confidence | Entropía cruzada, exactitud, Brier multiclase, matriz de confusión |
| Score | Ubicar el caso en una rúbrica ordenada | score, probabilities, confidence, legend | Entropía cruzada por nivel, MAE y RMSE del score, matriz por nivel |
| Noul | Estimar si una afirmación es verdadera | noul entre 0 y 1 | Entropía cruzada binaria, Brier binario, exactitud y matriz falso/verdadero |

## Arranque y resultados

Desde la raíz del proyecto, el arranque habitual incluye las tres cabezas del preset y sus pruebas:

```bash
bash start.sh
```

Para una ejecución explícita, con 2.000 ejemplos sintéticos, tres candidatos y hasta 40 épocas:

```bash
bash start.sh demo --rows 2000 --trials 3 --epochs 40 --output runs/preguntas_001
bash start.sh predict --run runs/preguntas_001 --state examples/example_state.json
open runs/preguntas_001/report.html
```

El directorio de salida debe ser nuevo. Los datos sintéticos permiten comprobar el flujo; no certifican rendimiento real. El comando open corresponde a macOS.

| Archivo del entrenamiento | Contenido |
| --- | --- |
| report.html | Interpretación, resultados por tipo, curvas con leyendas y matrices |
| report.json | Métricas, tipo de pregunta, losses por cabeza y época, prueba funcional |
| predictions.jsonl | Resultados de todos los casos de test y etiquetas reales; no repite el estado de entrada |
| loss_<pregunta>.png | Entrenamiento y validación de cada cabeza |
| confusion_<pregunta>.png / .csv | Matriz de clases o niveles |

## Contrato y datos de entrenamiento

config/brain.json y los tres presets incluyen Choice, Score y Noul. Para una pregunta de sí/no, usa kind: noul, una question concreta y dos options con identificadores false y true, en ese orden. Cada opción tiene meaning. Los contratos anteriores con kind: boolean siguen siendo válidos; no se modifica su hash al cargarlos.

Para Choice usa kind: choice y un catálogo de opciones con id y meaning. Para Score usa kind: score y opciones ordenadas de menor a mayor, con id, meaning y value numérico creciente. El campo score usa posiciones 0 a N−1. El campo heredado expected_score usa los valores personalizados value; no son necesariamente la misma escala.

El CSV mantiene las columnas de contexto, target__<id_de_pregunta> y __split. Choice y Score se etiquetan con el id de la opción o nivel observado; Noul se etiqueta con false o true. No se entrena Noul con probabilidades inventadas ni Score con puntuaciones continuas sin nivel. Se entrenan distribuciones supervisadas; después se calcula el resultado tipado. Cambiar opciones, preguntas o rúbricas requiere un nuevo contrato y entrenamiento.

La red comparte un codificador y tiene una salida softmax por pregunta. Noul usa dos clases, cuya entropía cruzada equivale a una pérdida binaria. Score aprende los niveles mediante entropía cruzada categórica y devuelve su media ponderada; no incorpora una pérdida ordinal adicional. La selección usa validación, la calibración usa su propia partición y test permanece separado.

## Lectura de los resultados

Con probabilidades de nivel bajo=0, medio=0,57 y alto=0,43, Score devuelve 1,43 en una escala de 0 a 2. No redondea el resultado. legend relaciona cada id con su posición y descripción. Las claves de probabilities conservan los ids del contrato para mantener el routing existente; no son claves numéricas como en la API de TypeSafe.

Noul=0,80 significa una probabilidad estimada del 80 % de que la afirmación sea verdadera. Noul=0,05 favorece falso. Noul=0,50 indica ambigüedad. No mide intensidad o gravedad y no lleva un campo confidence adicional.

En Choice y Score, confidence = 1 − H(p)/log(N), con H calculada sobre la distribución normalizada. Es 0 para una distribución uniforme y 1 para una distribución concentrada. Esta fórmula local no se presenta como la fórmula de Jev. No es una probabilidad de acierto: debe evaluarse con resultados etiquetados. max_probability sigue indicando la probabilidad de la opción ganadora.

La revisión y las reglas existentes continúan usando min_probability sobre la opción ganadora; no se sustituyen silenciosamente por confidence. Para Noul, un umbral de revisión de 0,8 deja pasar p≤0,2 y p≥0,8; los casos intermedios requieren revisión. El mapa confidence situado en la raíz del envelope conserva su significado anterior de probabilidad máxima por cabeza. Para la nueva confianza usa answers[id].confidence o el SDK tipado.

Los campos kind, choice, probabilities, max_probability y needs_review siguen presentes como metadatos compatibles del envelope. En Noul, el resultado público principal es noul; el SDK lo presenta sin una confianza separada. Los gates recalculan y verifican los campos derivados antes de dejarlos pasar.

## SDK Python

El SDK conserva answers como diccionario y añade question(id), con ChoiceAnswer, ScoreAnswer y NoulAnswer. El ejemplo usa una flota local ya iniciada con bash start.sh operate:

```python
import json
from pathlib import Path
from decision_brain_sdk import DecisionClient

context = json.loads(Path("examples/example_state.json").read_text())
with DecisionClient.from_fleet() as client:
    result = client.predict(
        "comercio.triaje", context,
        idempotency_key="primitivas-001",
    )
    category = result.question("clasificacion")
    level = result.question("nivel")
    priority = result.question("atencion_prioritaria")
    print(category.choice, category.probabilities, category.confidence)
    print(level.score, level.legend, level.confidence)
    print(priority.noul)
```

Usa una clave nueva para un caso nuevo. Una flota creada con contratos o releases anteriores debe conservar sus versiones: genera proyectos y una flota nuevos para probar los presets Noul, o prepara y evalúa nuevos releases por el procedimiento de promoción. No reemplaces manualmente contratos dentro de un release firmado. SDK y servidor deben actualizarse juntos para question(id); las respuestas antiguas siguen disponibles mediante answers.

## Harness de resultados numéricos

Las expectativas por etiqueta siguen vigentes. Para probar el valor continuo puedes utilizar rangos cerrados dentro de expected.answers:

```json
{
  "nivel": {"score": {"min": 1.4, "max": 1.5}},
  "atencion_prioritaria": {"noul": {"min": 0.7, "max": 0.9}}
}
```

El harness rechaza rangos invertidos, no finitos o fuera de escala. Una predicción fuera del rango falla el caso. Define los límites con casos etiquetados y criterios de negocio; no ajustes las expectativas para conseguir un PASS.

## Scaffolding

```bash
bash start.sh new --preset retail --brain-id comercio.preguntas --out proyectos/comercio_preguntas
cd proyectos/comercio_preguntas
bash start.sh
```

Los nuevos proyectos incluyen los tres tipos, validación de respuestas, schemas de gates, SDK, pruebas y esta documentación. Mantienen la capacidad de operar solos o detrás del gateway.

## Referencias de la semántica

Choice: https://docs.typesafe.ai/primitives/choice

Score: https://docs.typesafe.ai/primitives/score

Noul: https://docs.typesafe.ai/primitives/noul

Confianza: https://docs.typesafe.ai/confidence

Consultadas el 25 de septiembre de 2026. Se adopta la distinción funcional de los tipos, no compatibilidad total con la API de TypeSafe ni sus resultados de calidad.


La versión 0.11 amplía los escenarios retail y cambia el significado de sus preguntas de urgencia e impacto. Consulta [Entrenamiento realista](ENTRENAMIENTO_REALISTA.md) antes de reutilizar etiquetas antiguas.
