# Validación 0.14: algoritmos y router

140/140 pruebas del proyecto y 140/140 en un proyecto generado. La suite incluye comprobación numérica de gradientes, probabilidades ordinales, persistencia de todos los candidatos y uso de rutas distintas en el servicio. La ejecución completa entrena, compara, recarga y verifica 300 decisiones con el gate tipado; el harness aprueba 25/25.

Algoritmos: neural, ensemble de tres semillas, CORN ordinal y adaptación multisalida de SelectiveNet. El router reserva la mitad de validation para elegir y no consulta test ni calibration para fijar rutas. Esta ejecución conserva neural en todas las cabezas. El ensemble reduce ligeramente loss en test; no se usa ese resultado para modificar las rutas.

El gate de incertidumbre falla: cobertura conjunta 75,7 %, objetivo 90 %. La salida de la ejecución completa es 1 por calidad insuficiente; no hay fallo de software. La promoción queda bloqueada. Evaluación sintética y de desarrollo, no certificación para producción.

Evidencia actual en `evidencia/validacion_014/`. [Resumen HTML](RESULTADOS_014.html). Los archivos de versiones anteriores son históricos. La implementación NumPy adapta objetivos publicados; no reproduce los experimentos originales de los autores.
