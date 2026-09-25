# Evaluar decisiones

Después de `bash start.sh`, basta con:

```bash
bash start.sh harness
```

Se usa el último modelo entrenado y se crea una carpeta nueva para el HTML y JSON. El comando imprime su ubicación. No requiere volver a entrenar.

Para comparar dos modelos concretos:

```bash
bash start.sh harness --run runs/candidato --baseline runs/referencia
```

Ambos modelos deben usar el mismo contrato. Una regresión es un caso que aprobaba con la referencia y falla con el candidato; bloquea el resultado aunque mejore la tasa total.

## Casos

Edita config/harness_suite.json. Cada caso tiene id, context y expected. expected.answers mapea decisiones a opciones válidas; expected.action comprueba la ruta y expected.needs_review comprueba si se solicita revisión humana. Para una entrada inválida usa expect_error: true sin expected.

Los casos incluidos se derivan de los escenarios sintéticos del contrato. Son pruebas de funcionamiento, no un benchmark independiente. Añade casos revisados por especialistas antes de interpretar el resultado como calidad industrial. En contratos sin escenarios sintéticos sólo se crea inicialmente un caso de entrada inválida.

## Criterios

project.toml fija suite y min_pass_rate (1.0 por defecto). Puedes declarar run, output y baseline; las rutas son relativas al TOML. Una salida explícita no se sobrescribe: cambia el nombre para otra evaluación. Sin output el sistema elige una carpeta nueva automáticamente.

Salida 0 significa que cumple el umbral y no hay regresiones detectadas; 1 significa incumplimiento de expectativas; 2 significa error técnico. Un resultado 1 conserva el HTML. La ausencia de baseline se indica explícitamente.

El JSON guarda hashes de los artefactos y suite, expectativas, respuestas, comprobaciones y duración por caso. La duración no es un benchmark de carga. Los informes contienen respuestas del negocio; protégelos como tus datos. No se ejecutan acciones, no se entrenan modelos y no se activan releases desde el harness.
