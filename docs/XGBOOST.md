# XGBoost frente a nuestra red — experimento 0.13

No se incorpora XGBoost como backend operativo: en este experimento rindió peor. Permanece como comparación reproducible y opcional, fuera de las dependencias normales del proyecto.

Se usaron exactamente el mismo CSV, el mismo encoder TF-IDF/palabras y bigramas entrenado solo con train, y los mismos datos numéricos. Particiones: 1100 train, 300 validation, 300 calibration y 300 test. Calibration se divide 150/150 entre temperatura y cuantiles conformales. Cada algoritmo conserva su propia calibración. Tres configuraciones XGBoost (profundidades 2, 3 y 4), dos semillas por configuración, parada temprana sobre validation. La configuración se elige por loss media de validation y se conserva su primera semilla. No se seleccionó con test ni con el harness.

| Medida | Red neuronal 0.13 | XGBoost 3.1.3 |
|---|---:|---:|
| Loss media | 0,05113 | 0,39797 |
| Choice: exactitud | 100 % | 84,3 % |
| Noul: exactitud | 98,7 % | 68,7 % |
| Score: nivel más probable | 100 % | 93,7 % |
| Harness conocido | 25/25 | 19/25 |
| Casos automatizados de 300 | 174 (58 %) | 118 (39,3 %) |
| Errores entre automatizados | 0/174 | 51/118 |
| Cobertura conjunta de conjuntos | 74 % | 39 % |

Un error automatizado significa que al menos una cabeza difiere de su etiqueta. No evalúa consecuencias económicas de una acción. Cero errores observados en 174 casos no demuestra riesgo cero. La cobertura de conjuntos mide inclusión de las etiquetas verdaderas, no porcentaje de automatización.

XGBoost falló los seis casos de reclamación del harness. Usar árboles sobre TF-IDF no incorpora un modelo semántico contextual. Este ensayo no descarta XGBoost para variables de negocio tabulares, categorías y señales agregadas; esa hipótesis requiere otro dataset y evaluación. No se probó una combinación neuronal + árboles.

Ambos fallan el gate de cobertura conjunta de conjuntos (objetivo 90 %). La red mejora el harness respecto al modelo 0.12 proporcionado por el usuario (21 → 25 casos), con 0 regresiones en esa suite. Sin embargo, el test sigue siendo sintético y ya fue inspeccionado durante el desarrollo; no es una certificación independiente. Las expresiones difieren por partición, de modo que intercambiabilidad no está asegurada. El siguiente trabajo debe reducir revisión excesiva y comprobar cobertura con datos representativos, sin ajustar para aprobar este test.

La comparación evalúa el procedimiento completo seleccionado, no igualdad de coste computacional ni una búsqueda exhaustiva. El script también registra latencias locales con modelos cargados: excluyen encoder, servidor y red y no son SLA del servicio.

## Reproducir la comparación

Requiere el entorno del proyecto y XGBoost 3.1.3 instalado por separado. No es necesario instalar XGBoost para iniciar o entrenar la fábrica. La ejecución publicada se realizó en Linux CPU; no se validó la instalación de XGBoost en macOS.

```bash
PYTHONPATH=src:sdk/src .venv/bin/python research/compare_xgboost.py --reference docs/evidencia/validacion_013/model --data docs/evidencia/validacion_013/dataset.csv --out runs/comparacion_xgboost_nueva
```

Resultado completo: `docs/evidencia/validacion_013/xgboost/comparison.json`. Modelos XGBoost serializados en JSON en esa misma carpeta. El modelo operativo sigue siendo la red NumPy, con calibración y abstención. Fuentes técnicas: https://xgboost.readthedocs.io/en/release_3.1.0/python/python_api.html y https://arxiv.org/abs/1603.02754 .
