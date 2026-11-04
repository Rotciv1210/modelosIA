# Desarrollo por fases

Para cada fase se indica qué se implementó, cómo probarlo, los posibles problemas y si cumple los requisitos.

> Las pruebas se ejecutan con `python -m pytest` desde `tabu_local/`. Ninguna necesita Ollama.

---

## Fase 1 · Arquitectura y decisiones de diseño
- **Implementado:** la estructura modular que se describe en `README.md §10` y `MEMORIA.md §2`, y la configuración en `config.json` con validación en `config.py` (rechaza claves desconocidas y valores fuera de rango).
- **Probar:** `python -c "import config; print(config.cargar_config())"`. Si pones `"rondas": 0`, aparece un error claro.
- **Problemas:** si se edita mal el JSON, sale un `ConfigError` legible, no una traza.
- **Requisitos:** ✔ los modelos se cambian sin tocar el código · ✔ todo es configurable (rondas, intentos, prohibidas, *timeout*, modelos y puntuación).

## Fase 2 · Conexión con Ollama y gestión de modelos
- **Implementado:**
  - `models/ollama_client.py`: `/api/chat` sin *streaming*, con semilla, `num_predict`, `format: json` y `keep_alive`.
  - Errores tipados: `OllamaUnavailableError`, `ModelNotFoundError`, `OllamaTimeoutError` y `OllamaResponseError`.
  - Eliminación de los bloques `<think>`.
  - Bloqueo de hosts no locales y de modelos `*-cloud`.
  - `models/model_manager.py`: lista los modelos instalados, los compara con la configuración (`llama3.2` = `llama3.2:latest`) y da las instrucciones `ollama pull`.
- **Probar:** `python main.py modelos` · `pytest tests/test_ollama_client.py`.
- **Problemas:** la primera llamada a cada modelo tarda porque lo carga en memoria (por eso `keep_alive`). Si `timeout_s` es bajo, ese primer turno puede fallar; se registra y se reintenta.
- **Requisitos:** ✔ API local de Ollama · ✔ modelo no instalado · ✔ Ollama no disponible · ✔ *timeout* · ✔ errores de conexión.

## Fase 3 · Motor del juego y tres roles
- **Implementado:**
  - `game/prompts.py`: un prompt por rol, que recibe solo la información de ese rol.
  - `game/roles.py`: Descriptor y Adivinador.
  - `game/turn_manager.py`: el turno con pistas adicionales tras cada fallo.
  - `game/game_engine.py`: rondas, alternancia de equipos y mazo sin repetición.
  - `game/referee.py`: limpieza y validación de respuestas.
- **Probar:** `python main.py jugar --simulado --sin-pausa` · `pytest tests/test_game.py`.
- **Problemas:** con modelos muy pequeños el adivinador a veces ignora el formato JSON. El árbitro extrae la palabra del texto libre y, si no puede, reintenta.
- **Requisitos:** ✔ descriptor, adivinador y vigilante · ✔ intentos limitados · ✔ el adivinador nunca ve la secreta ni las prohibidas (hay una prueba específica) · ✔ el programa no se bloquea por una respuesta mala.

## Fase 4 · Detección de infracciones
- **Implementado:**
  - `detection/text_normalizer.py`.
  - `detection/forbidden_checker.py`: exacta, morfológica, derivada, compuesta, frase, deletreo y traducción.
  - `detection/semantic_judge.py`: JSON validado, umbral y reintento.
  - Integración en el árbitro: el vigilante solo se consulta si las reglas no detectan nada, y una pista con infracción no llega nunca al adivinador.
- **Probar:** `pytest tests/test_detection.py`. Para verlo con trampas simuladas: `python main.py jugar --simulado`.
- **Problemas:** raíces aproximadas (ver la memoria, §4.3) y ruido del vigilante. Se mitigan con el umbral, el modo consultivo y el registro separado.
- **Requisitos:** ✔ todos los puntos A y B del enunciado · ✔ JSON con `infraccion`, `palabra_detectada`, `tipo_infraccion`, `justificacion` y `nivel_confianza` · ✔ el vigilante no ve el marcador ni a los equipos, y no puede cambiar las reglas.

## Fase 5 · Tarjetas y validación
- **Implementado:**
  - `cards/cards.json`: 52 tarjetas en español, cada una con 5 prohibidas, 2 extra, categoría, dificultad y traducciones.
  - `cards/card_validator.py`, `cards/deck.py`: mazo con semilla, filtros y sin repetición.
  - `cards/card_generator.py`: generación con un modelo local, validación y revisor opcional.
- **Probar:** `python main.py tarjetas validar` · `pytest tests/test_cards.py` · con Ollama: `python main.py tarjetas generar -n 3`.
- **Problemas:** la relevancia de las prohibidas solo se puede comprobar con un modelo (revisor), que también se equivoca. Por eso las tarjetas generadas se guardan aparte para revisarlas.
- **Requisitos:** ✔ 3–5 prohibidas · ✔ categoría y dificultad · ✔ sin secretas repetidas · ✔ revisión automática previa · ✔ el juego funciona sin generación automática.

## Fase 6 · Registro de partidas y puntuación
- **Implementado:**
  - `game/records.py`: todos los campos que pide el enunciado, más los veredictos, los tiempos por rol y las descripciones rechazadas.
  - `game/game_logger.py`: JSON por partida, guardado atómico tras cada turno.
  - `game/scoring.py`: +1 por acierto y −1 por infracción (configurables); marcador con desempate.
  - `python main.py historial [ID]`.
- **Probar:** juega una partida y ejecuta `python main.py historial` · `pytest tests/test_scoring.py`.
- **Problemas:** con la opción `fin_turno_por_infraccion = false` un turno puede tener puntuación negativa aunque se acierte. Es intencionado.
- **Requisitos:** ✔ registro JSON completo · ✔ consulta del historial · ✔ penalizaciones configurables.

## Fase 7 · Experimento y estadísticas
- **Implementado:**
  - `experiment/experiment_runner.py`: condiciones anidadas, misma semilla por turno en todas las condiciones, orden de condiciones aleatorio, guardado incremental y reanudación.
  - `experiment/metrics.py`: media, DT, IQR, IC de Wilson, IC bootstrap y diferencias pareadas.
  - `experiment/plots.py`: 7 gráficos PNG.
- **Probar:** `python main.py experimento --simulado --tarjetas 10` (datos sintéticos, marcados como tales) · `pytest tests/test_experiment.py`.
- **Problemas:** la duración puede ser de horas. Haced primero una versión corta y usad `--reanudar` si se corta.
- **Requisitos:** ✔ condiciones A, B y C · ✔ mismas tarjetas, modelos y semillas · ✔ las 6 métricas · ✔ CSV y gráficos · ✔ dispersión · ✔ **no se han inventado resultados**: quedan pendientes de ejecución.

## Fase 8 · Pruebas automáticas
- **Implementado:** 87 pruebas en 7 ficheros (`tests/`). Usan `ScriptedClient` (respuestas guionizadas que registran cada prompt) y `SimulatedClient`.
- **Probar:** `python -m pytest` → `87 passed`.
- **Problemas:** las pruebas validan la lógica del árbitro, no la calidad de los modelos reales.

## Fase 9 · README y memoria
- **Implementado:** `README.md` (instalación, Ollama, modelos, ejecución, experimento, pruebas e interpretación) y `docs/MEMORIA.md` (los 10 apartados, con los resultados pendientes).

## Fase 10 · Integración
- **Comprobado en el entorno de desarrollo (sin Ollama):**
  - la suite completa pasa;
  - `jugar --simulado` completa una partida, guarda el JSON y se ve en `historial`;
  - `experimento --simulado` genera los CSV, el JSONL y los PNG;
  - `tarjetas validar` da 52/52 válidas;
  - `modelos` informa correctamente de que Ollama no está disponible.
- **Pendiente en vuestra máquina:**
  1. `ollama pull` de los modelos y `python main.py modelos`.
  2. `python main.py demo` para probar los prompts con modelos reales.
  3. Un experimento corto (`--tarjetas 5 --repeticiones 1`) para medir tiempos.
  4. El experimento completo.

## Ampliación · Interfaz gráfica
- **Implementado:**
  - `gui/server.py`: servidor web local en 127.0.0.1, solo con la biblioteca estándar, que reutiliza el mismo motor.
  - `gui/static/index.html`: configuración de modelos y reglas, tablero en directo (tarjeta, pistas, veredictos, respuestas, marcador), pausa entre turnos, detener, ventana del ganador e historial.
- **Probar:** `python main.py gui` (o `python main.py gui --simulado`) · `pytest tests/test_gui.py`.
- **Problemas:** si el puerto 8765 está ocupado, usa `--puerto`. Al cerrar la terminal se cierra también la interfaz.
