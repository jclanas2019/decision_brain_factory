# Configuración TOML

project.toml es configuración de ejecución del harness. pyproject.toml define el paquete Python. El arranque instala ambos comandos: .venv/bin/decision-brain y .venv/bin/decision-harness.

La sección [harness] admite suite, min_pass_rate, run, output y baseline. Sin run se usa runs/latest_model.json; sin output se crea una carpeta nueva. Rutas TOML se resuelven respecto al archivo y se normalizan (incluidos los alias /var y /private/var en macOS). Los argumentos explícitos prevalecen sobre TOML. Una clave desconocida o tipo incorrecto es error.

```bash
bash start.sh harness --project project.toml
```

El arranque completo pasa las rutas de la sesión explícitamente, conserva la suite y umbral definidos, y actualiza el puntero del último modelo al completar el entrenamiento. Los contratos de negocio siguen en config/brain.json. El servicio se configura mediante variables de entorno.
