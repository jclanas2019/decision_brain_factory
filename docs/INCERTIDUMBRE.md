# Abstención calibrada — versión 0.13.0

El entrenamiento sigue siendo supervisado. No utiliza Laya, la API de Jev ni RLCD. Esta versión mejora la calibración y la política de abstención; no incorpora detección semántica garantizada de contradicciones.

Se conserva train para optimización y validation para autoresearch. Calibration se divide aleatoriamente en dos partes disjuntas: la primera ajusta una temperatura por cabeza minimizando entropía cruzada; la segunda estima conjuntos conformales por clase con puntuación 1 − probabilidad de la etiqueta real. Test no participa en ninguno de estos ajustes.

El cuantil usa el orden ceil((n+1)(1−alpha)). Si faltan muestras de una clase, se conserva esa clase en el conjunto. El presupuesto nominal de error conjunto es 0,10, repartido entre las cabezas. Bajo intercambiabilidad de datos de calibración y futuros, esta construcción busca cobertura conjunta al menos 90 %. No significa 90 % de exactitud entre los casos automatizados, ni aplica automáticamente a datos fuera de distribución.

Una respuesta solo se automatiza si cada cabeza conserva una única opción que coincide con su argmax y supera el umbral original del contrato. Las probabilidades no se alteran para simular duda. Cada cabeza informa prediction_set y review_reasons; el gateway verifica su coherencia y no permite omitir una revisión exigida por el contrato. Los cuantiles se guardan en model.json, sujeto a la integridad de releases. Modelos antiguos sin política conservan el comportamiento anterior; deben reentrenarse para usarla.

## Uso

Desde la carpeta del proyecto:

```bash
bash start.sh
```

El arranque ejecuta pruebas, entrenamiento y harness. Abre report.html o runs/latest.html. El informe del modelo incluye una comparación de automatización y errores frente al umbral fijo sobre las mismas probabilidades. Esa comparación aísla la política; no debe confundirse con una mejora respecto a un modelo anterior.

```bash
bash start.sh new --preset retail --brain-id comercio.triaje --out proyectos/comercio_v013
cd proyectos/comercio_v013
bash start.sh
```

Los proyectos nuevos incluyen el algoritmo y sus pruebas. No sobrescribas modelos publicados ni carpetas existentes.

## Interpretación

| Resultado | Lectura |
|---|---|
| Conjunto vacío | Ninguna opción supera su requisito de calibración; revisión |
| Varias opciones | La evidencia no permite elegir una sola; revisión |
| Una opción | Candidata a automatización, sujeta al umbral del contrato |
| Menos errores y menor cobertura | Se evita parte del riesgo a costa de más revisión |
| Cero automatizaciones | No hay exactitud selectiva que estimar; se muestra nulo |

Los casos del harness siguen siendo una prueba independiente y sus expectativas no se cambian para favorecer esta versión. Un harness fallido impide declarar aptitud de calidad. Mensajes fuera de dominio pueden seguir recibiendo una respuesta única incorrecta y segura. Se necesitan datos reales separados por cliente, período o grupo y pruebas específicas de negación y ambigüedad.

Referencia metodológica: Angelopoulos y Bates, *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification*, https://arxiv.org/abs/2107.07511 .

El gate empírico exige cobertura conjunta observada de al menos 1−alpha y al menos una automatización evaluable. Si falla, `assurance.passed` es falso, el arranque completo termina con código 1 y conserva los informes. Las comprobaciones AutoEvals de etiquetas y el harness se muestran por separado; aprobarlos no elimina este bloqueo.
