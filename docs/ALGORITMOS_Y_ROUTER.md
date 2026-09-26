# Algoritmos y router — 0.14

Esta versión implementa cuatro candidatos locales y un router de algoritmos. El router de algoritmos selecciona qué modelo calcula cada cabeza de decisión. El router de eventos existente conserva su función independiente: llevar eventos entre microcerebros a través de contratos y gateways.

## Un comando

```bash
bash start.sh compare
```

Ejecuta pruebas de software, entrena los candidatos, calibra, compara, guarda el router y ejecuta el harness. Abre el informe de la sesión. Dentro del informe del modelo aparece el enlace **Comparación de algoritmos y router**. El router queda guardado como último modelo para `predict`. Los fallos de calidad producen código 1 y conservan el informe; no significan que el software haya fallado ni autorizan producción.

```bash
bash start.sh predict --state examples/example_state.json
```

Cada respuesta del router indica `algorithm`. El SDK, servicio, gateway y registro de releases usan el mismo modelo guardado. Un `selection_score` de SelectiveNet expresa aceptación aprendida, no probabilidad calibrada de corrección. Puede añadir revisión, nunca anular la revisión exigida por el contrato o por los conjuntos conformales.

Para datos propios con las cuatro particiones y etiquetas del contrato:

```bash
bash start.sh compare --data data/decisiones.csv --epochs 40 --no-open
```

Para crear un proyecto independiente:

```bash
bash start.sh new --preset retail --brain-id comercio.triaje --out proyectos/comercio_multi
cd proyectos/comercio_multi
bash start.sh compare
```

`bash start.sh` mantiene el entrenamiento neuronal anterior. `compare` activa la comparación multialgoritmo. `--trials` controla autoresearch del motor neuronal, no aumenta los cuatro candidatos fijos del comparador. El presupuesto total de entrenamiento procede de research_policy.json; se requieren al menos cinco experimentos permitidos (tres redes para el ensemble, una CORN, una selectiva).

## Qué se implementó

| Nombre | Entrenamiento y predicción | Alcance |
|---|---|---|
| neural | Red compartida tanh con cabezas softmax y entropía cruzada | Referencia local |
| ensemble | Tres inicializaciones independientes; promedio de probabilidades | Agregación probabilística inspirada en Deep Ensembles; sin entrenamiento adversarial del paper |
| corn | Cabezas Score con subtareas binarias condicionadas y probabilidades acumuladas; otras cabezas softmax | Adaptación NumPy de CORN; no cambia Choice ni Noul a variables ordinales |
| selective | Clasificación, selector y cabezas auxiliares entrenadas conjuntamente; riesgo ponderado más penalización por cobertura y pérdida auxiliar | Adaptación multisalida de SelectiveNet, objetivo de cobertura blanda 80 %, umbral de aceptación 0,5 |
| router | Rutas fijas por cabeza, seleccionadas en validación reservada | No elige el modelo de mayor confianza por petición |

Las implementaciones siguen objetivos publicados, no reproducen sus arquitecturas, conjuntos de datos ni resultados originales. Todos los candidatos comparten el mismo encoder numérico + TF-IDF para aislar el efecto del algoritmo. No se evaluaron SetFit, NLI ni un encoder Transformer en esta entrega. No hay dependencia de Jev, Laya, API externa o RLCD. No es aprendizaje por refuerzo.

## Separación de datos

Train ajusta encoder y pesos. Validation se divide con semilla fija: mitad para seleccionar época y mitad para elegir el algoritmo de cada cabeza. Calibration se divide después: mitad para temperatura y mitad para conjuntos conformales. El router queda congelado antes de acceder a calibration, test y harness. El conjunto de test usado aquí ya fue examinado durante el desarrollo previo: estos resultados son evidencia de desarrollo, no aceptación independiente.

La política está en `config/algorithm_router.json`. Selecciona por menor log loss de validación, exige una mejora absoluta mínima 0,001 frente a neural y al menos 50 % de aceptación del selector. Si no hay mejora suficiente, conserva neural. No se cambian rutas por el resultado de test. Cambiar la política exige un entrenamiento y una nueva versión; no se edita un release publicado.

El comparador usa una inicialización para CORN y selective, y tres para ensemble. No es una búsqueda exhaustiva ni una comparación con igual coste de cómputo. Guardamos los índices de partición de validación, semillas de construcción, configuración, métricas de selección e historia para auditarla.

## Persistencia y pruebas

`model.json` describe el grafo de algoritmos, rutas, temperaturas y política de abstención. `weights.npz` contiene exclusivamente matrices numéricas. La carga no ejecuta pickle ni código suministrado por el artefacto. Los hashes de releases cubren ambos archivos. Se comprueba que las probabilidades, decisiones y revisión permanecen iguales al recargar y que el gate tipado acepta la respuesta.

Las pruebas incluyen gradientes por diferencias numéricas para CORN y selective, monotonicidad de probabilidades ordinales, reconstrucción del ensemble y router, rechazo de pesos no finitos, selección por validación y un recorrido registro → carga → servicio → response gate con CORN, ensemble y selective en cabezas distintas.

## Referencias

Deep Ensembles: https://proceedings.neurips.cc/paper/2017/hash/9ef2ed4b7fd2c810847ffa5fa85bce38-Abstract.html

SelectiveNet: https://proceedings.mlr.press/v97/geifman19a.html

CORN: https://arxiv.org/abs/2111.08851

No se promete que esos resultados publicados se transfieran a nuestras tareas. Los resultados medidos de esta entrega están en `docs/evidencia/validacion_014/model/comparison.html`.
