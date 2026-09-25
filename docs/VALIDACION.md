# Validación de la versión 0.9

Ejecución en Linux/Python 3.12. La documentación se consolidó: README de entrada, GUIA_DE_USO en Markdown/HTML, referencia SDK y este registro. Se retiraron manuales duplicados y logs históricos de otras versiones del paquete entregado.

| Verificación | Resultado |
|---|---|
| Suite completa | 95 pruebas aprobadas |
| Proyecto generado por la fábrica | 95 pruebas aprobadas |
| SDK instalado desde wheel en un entorno aislado | 10 pruebas del SDK aprobadas; sin numpy ni paquete del servidor |
| Instalación editable del sistema completo | Imports del servidor y del SDK correctos |
| Integración HTTP real | Catálogo, predicción tipada, replay idempotente, consumidor automático, consulta de decisiones, trazas y métricas aprobados |
| Documentación | Sintaxis de ejemplos Python/JSON, estructura HTML e índice comprobados |

Las diez pruebas del SDK están incluidas en las 95 del sistema; se repitieron además contra la distribución instalada de forma independiente. No son 105 pruebas distintas.

El cliente no reintenta automáticamente, no ejecuta acciones y no modifica modelos. La versión y el cuerpo quedan fijados en PreparedDecision. Se prueban timeout, códigos HTTP, protección de mensajes de error, respuesta probabilística inválida, replay, filtros y propagación de traza.

La compatibilidad mínima declarada del SDK es Python 3.10, pero solo se ejecutó con Python 3.12 en este entorno. No se ejecutó una matriz completa de Python, macOS nativo, Docker o carga productiva. El HTML se verificó estructuralmente; no se certifica su renderizado en todos los navegadores.

Esta entrega no corrige la calidad insuficiente del modelo logístico ni añade expediente global/revisión humana resolutiva. La guía documenta esas limitaciones. Los resultados de validación actuales están en docs/evidencia/.
