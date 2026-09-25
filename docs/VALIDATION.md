# Verificación de la reorganización 0.5.0

El código se convirtió en el paquete decision_brain bajo src/. Las pruebas están en tests/, la configuración en config/, la documentación en docs/ y los archivos de contenedores en deploy/. Las referencias internas, comandos, instalación editable y copia de proyectos se adaptaron a estas rutas.

Se ejecutaron las 37 pruebas después del cambio de estructura. También se verificó la creación de un proyecto independiente que conserva la organización. Las verificaciones anteriores de macOS simulado y calidad de modelos se conservan abajo como antecedentes, no como nuevas ejecuciones nativas.

# Verificación de la entrega 0.4.0

Esta entrega consolida el proyecto ejecutable y su fábrica en una sola carpeta. No requiere copiar parches ni reutilizar una entrega anterior.

| Verificación ejecutada | Resultado |
| --- | --- |
| Suite de software | 37 pruebas, cero fallos y cero errores |
| Instalación aislada de dependencias y paquete | Completada; pip check sin incompatibilidades |
| Retail, flujo completo por defecto | Completado dos veces; harness 4/4 |
| Predicción desde el último modelo guardado | Completada con respuestas tipadas e interpretación |
| Harness independiente, sin especificar run ni output | Completado, 4/4; carpeta nueva |
| Servicio HTTP real con uvicorn | Readiness 200, predicción autenticada correcta, acceso sin credencial 401 |
| Proyecto generado de logística | Creado y ejecutado desde ruta con espacios, acentos y enlace simbólico |
| Entorno con LANG=C, entrada PYTHONIOENCODING=ascii y TMPDIR enlazado | El arranque impuso UTF-8; las 37 pruebas aprobaron |
| Proyecto generado de manufactura | Entrenamiento, recarga, métricas, HTML y harness completados |
| HTML de la última sesión retail | Ocho archivos leídos como UTF-8 y todos sus enlaces locales/figuras verificados |

## Fallos encontrados y resueltos

Las pruebas TOML comparaban rutas canónicas contra alias sin normalizar. Se corrigieron y se añadió un caso con enlaces simbólicos. Lecturas, escrituras y procesos usaban codificaciones implícitas; ahora usan UTF-8, y los registros se muestran en páginas HTML con charset declarado. Se eliminaron copias de plantillas obsoletas y los instaladores incrementales de la distribución. Los fixtures técnicos usan un contrato de prueba separado del contrato de negocio.

Se corrigió la selección del último modelo para predicción y evaluación independiente, la generación de salidas únicas y los mensajes de fallo. Se agregó validación de pesos, temperaturas y distribuciones de probabilidad. La promoción rechaza métricas vacías o matrices de confusión inconsistentes.

Durante la primera instalación de verificación un paquete descargado produjo BadZipFile. Una segunda instalación completó el entorno. El instalador final incluye un reintento limitado sin caché para ese error concreto y conserva diagnóstico. Una segunda instalación desde cero, en la ruta de logística con espacios, completó el flujo.

## Resultados de calidad, separados de los errores técnicos

Los presets no son modelos certificados. En los casos sintéticos evaluados, retail aprobó 4/4, logística 2/4 y manufactura 3/4. Los dos últimos devolvieron salida 1 y conservaron los informes: el software funcionó, pero los modelos incumplieron expectativas. No se ajustaron los umbrales ni se cambiaron las etiquetas para ocultar estos resultados. Requieren datos y validación de dominio antes de uso operativo.

## Límites de la verificación

Ejecución realizada en Linux x86_64 con Python 3.12.14. No se dispone de un Mac para ejecutar pruebas nativas; se reprodujeron enlaces simbólicos, temporales con alias, rutas con espacios y condiciones de codificación. La apertura con `open` está implementada para macOS, pero no se ejecutó allí. Se incluye CI para Linux/macOS y Python 3.12/3.13; agregarlo no equivale a haber ejecutado esa matriz.

No se verificó un despliegue Docker ni carga productiva en esta revisión. La búsqueda de hiperparámetros no es auto-research autónomo. El diseño local no utiliza la API de JEV ni acredita equivalencia con sus mecanismos internos.
