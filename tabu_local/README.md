# Tabú entre modelos locales

Juego de Tabú en el que **todos los jugadores son modelos de lenguaje de pesos abiertos ejecutados en tu ordenador con Ollama**. Hay tres roles:

- El **descriptor** conoce la palabra secreta y las prohibidas.
- El **adivinador** solo recibe las pistas.
- El **vigilante** busca trampas.

El programa hace de **árbitro**: reparte la información, detecta infracciones, puntúa, guarda cada ronda en JSON y ejecuta un experimento para responder a esta pregunta: *¿cómo afecta el número de palabras prohibidas (3, 5 o 7) al rendimiento?*

Durante las partidas no se envía nada a Internet. El cliente rechaza los hosts que no son locales y también los modelos `*-cloud` de Ollama.

---

## 1. Requisitos

| Componente | Versión / nota |
|---|---|
| Python | 3.11 o superior |
| Ollama | Versión reciente (https://ollama.com/download) |
| RAM | ~8 GB para modelos de 2–3 B parámetros. Con 16 GB se pueden usar modelos de 7–8 B |
| Dependencias Python | `requests`, `matplotlib`, `pytest` (en `requirements.txt`) |

## 2. Instalación de Python y del proyecto

```bash
# Comprueba la versión (en Windows: py --version)
python3 --version

cd tabu_local
python3 -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## 3. Instalación y configuración de Ollama

1. Descarga e instala Ollama desde https://ollama.com/download (Windows, macOS o Linux).
   En Linux también puedes usar `curl -fsSL https://ollama.com/install.sh | sh`.
2. Arranca el servidor. La aplicación de escritorio lo hace sola; en terminal, ejecuta `ollama serve`.
3. Comprueba que responde: `curl http://localhost:11434/api/version`.

## 4. Descarga de modelos

Configuración por defecto (modelos pequeños que funcionan en un portátil):

```bash
ollama pull llama3.2:3b     # Meta Llama 3.2, 3B
ollama pull qwen2.5:3b      # Alibaba Qwen 2.5, 3B
ollama pull gemma2:2b       # Google Gemma 2, 2B (vigilante)
```

Puedes usar cualquier otro modelo del catálogo de Ollama: `qwen2.5:7b`, `mistral:7b`, `gemma3:4b`, `llama3.1:8b`… Los modelos que «piensan», como `qwen3` o `deepseek-r1`, también sirven, porque el cliente elimina los bloques `<think>`. Eso sí, son más lentos.

Comprueba que todo está listo:

```bash
python main.py modelos
```

## 5. Configuración de modelos y reglas (`config.json`)

No hace falta tocar el código. Puedes editar `config.json` o pasar otro fichero con `--config`.

```jsonc
"equipos": [
  {"nombre": "Equipo Azul", "descriptor": "llama3.2:3b", "adivinador": "qwen2.5:3b"},
  {"nombre": "Equipo Rojo", "descriptor": "qwen2.5:3b", "adivinador": "llama3.2:3b"}
],
"vigilante": "gemma2:2b"
```

| Clave (`juego`) | Significado | Defecto |
|---|---|---|
| `rondas` | Rondas por partida (en cada una juega un turno cada equipo) | 3 |
| `intentos_por_tarjeta` | Respuestas que puede dar el adivinador (una pista nueva por intento) | 3 |
| `num_prohibidas` | Palabras prohibidas por tarjeta (1–7; el juego normal usa 3–5) | 5 |
| `puntos_acierto` / `penalizacion_infraccion` / `penalizacion_invalida` | Puntuación | 1 / 1 / 0 |
| `fin_turno_por_infraccion` | Si hay trampa, se pierde la tarjeta (como en el Tabú real) | true |
| `max_palabras_descripcion` | Longitud máxima; las descripciones más largas se recortan por la última frase completa | 40 |
| `reintentos_respuesta_invalida` | Reintentos ante respuestas vacías, repetidas o sin formato | 2 |
| `usar_vigilante_semantico` | Activa el tercer modelo | true |
| `vigilante_modo` | `penaliza` o `consultivo` (solo registra) | penaliza |
| `umbral_confianza_vigilante` | Confianza mínima para que una sospecha del vigilante cuente | 0.8 |
| `ficheros_tarjetas` | Mazos que se cargan | `cards/cards.json` |

En `ollama` puedes configurar `num_gpu`, `timeout_s` (tiempo máximo de respuesta), `temperature`, `seed` (reproducibilidad) y `max_tokens`.

## 6. Ejecución

### Interfaz gráfica (recomendada para clase)

```bash
python main.py gui
```

Se abre el navegador en `http://127.0.0.1:8765`. La página funciona sin Internet y el servidor solo escucha en tu ordenador. Desde ella:

1. **Configuras la partida.** Al empezar, la app carga en memoria los modelos elegidos y muestra el progreso; la espera ocurre una sola vez. Antes de eso: comprueba Ollama y muestra los modelos instalados en desplegables (descriptor y adivinador de cada equipo, de 1 a 4 equipos, y vigilante). También eliges rondas, prohibidas e intentos.
2. **Sigues la partida en directo** (tema oscuro pensado para proyector):
   - la tarjeta en grande con la palabra secreta y las prohibidas;
   - la pista del descriptor y el veredicto del vigilante;
   - si la pista llega al adivinador o se anula por trampa (la prohibida usada aparece tachada en la tarjeta);
   - la respuesta del adivinador;
   - un indicador de qué modelo está «pensando»;
   - el marcador con un panel por equipo (puntos, «+1»/«−1» del último turno, modelos con su avatar);
   - fichas de intentos y un cronómetro del turno sobre la tarjeta;
   - la palabra que provoca una infracción, tachada dentro de la pista;
   - los turnos anteriores plegados abajo: al pulsar uno se vuelve a ver su conversación.
3. **Controlas el ritmo:** en modo presentación avanzas con **Siguiente turno** (o la tecla Enter). Con **Detener** cortas la partida y se guarda lo jugado. La tecla **F** activa la pantalla completa.
4. **Ves el ganador** en una ventana al terminar, y el resumen de todos los turnos.
5. **Consultas el historial:** la pestaña Historial muestra todas las partidas guardadas con el detalle de cada turno.

Para cerrarla, pulsa `Ctrl+C` en la terminal. Otras opciones:

- `python main.py gui --simulado`: prueba sin Ollama.
- `--puerto 8080`: usa otro puerto si el 8765 está ocupado.
- `--no-abrir`: no abre el navegador automáticamente.

### Consola

```bash
python main.py                 # menú interactivo
python main.py demo            # demostración guiada para clase (pausa entre turnos)
python main.py jugar           # partida con config.json
python main.py jugar --rondas 2 --prohibidas 3 --sin-vigilante
python main.py historial       # lista de partidas
python main.py historial partida_2026   # detalle (vale un prefijo del ID)
python main.py tarjetas validar
python main.py tarjetas generar -n 5 --modelo qwen2.5:3b
```

**Modo de prueba sin Ollama:** añade `--simulado` a `jugar`, `demo` o `experimento`. Se usa un simulador aleatorio, no un modelo. Sirve para comprobar que el programa funciona, nunca para sacar conclusiones. Todo lo que genera queda marcado como `SIMULADO`.

### Modo demostración (clase)

`python main.py demo`:

1. Comprueba Ollama y lista los modelos locales.
2. Permite elegir los modelos de cada equipo y del vigilante.
3. Juega la partida turno a turno, con Enter para avanzar. En cada turno muestra:
   - la tarjeta (al público);
   - la pista del descriptor;
   - el veredicto del vigilante;
   - si la pista llega al adivinador o se anula por trampa;
   - la respuesta del adivinador y el marcador.
4. Al final muestra la clasificación y el ganador.

Usa `--sin-pausa` para que avance solo.

## 7. Experimento

```bash
python main.py experimento                          # usa la sección "experimento" de config.json
python main.py experimento --tarjetas 10 --repeticiones 1   # versión corta
python main.py experimento --reanudar exp_20261103_101500   # continuar uno interrumpido
python main.py analizar data/results/exp_20261103_101500     # recalcular estadísticas
```

**Coste:** turnos = repeticiones × tarjetas × equipos × 3 condiciones. Con la configuración por defecto son 2 × 30 × 2 × 3 = **360 turnos**. Cada turno hace entre 3 y 9 llamadas a modelos. Con modelos de 3B en un portátil sin GPU puede tardar varias horas. Lanza primero una versión corta para medir. El experimento guarda cada turno al terminarlo y se puede reanudar.

Resultados en `data/results/<id>/`:

| Fichero | Contenido |
|---|---|
| `turnos.csv` | Una fila por turno (condición, tarjeta, equipo, resultado, infracciones, tiempos…) |
| `registros.jsonl` | Registro completo de cada turno (pistas, respuestas, veredictos) |
| `resumen_condiciones.csv` | Por condición: % de acierto con IC 95 %, infracciones (media, DT, IC), inválidas, intentos, puntuación (media, DT, IQR, IC), tiempos |
| `resumen_equipos.csv`, `resumen_dificultad.csv` | El mismo resumen desglosado |
| `comparaciones.csv` | Diferencias pareadas entre condiciones (misma tarjeta/equipo/repetición) con IC 95 % bootstrap |
| `mcnemar.csv` | Prueba exacta de McNemar sobre los aciertos pareados, con y sin los turnos penalizados por el vigilante |
| `acierto_sin_infraccion.csv` | Acierto solo en turnos sin trampas (separa «hacer trampa» de «describir peor») |
| `auditoria_vigilante.json` | Cuántas veces acusó el vigilante, cuántas sin pruebas y cuántas penalizó |
| `graficos/*.png` | Gráficos comparativos |
| `config.json`, `tarjetas.json` | Configuración y tarjetas exactas usadas |

## 8. Pruebas

```bash
python -m pytest
```

Hay 90 pruebas y ninguna necesita Ollama: usan clientes falsos. Cubren:

- normalización y detección de trampas;
- vigilante;
- tarjetas y mazo;
- turnos, puntuación y aislamiento de información;
- recuperación ante respuestas inválidas y *timeouts*;
- registro JSON;
- experimento completo y reanudación;
- cliente HTTP;
- API de la interfaz gráfica (partida completa, pausas y detener).

## 9. Interpretación de resultados

- **% de acierto (IC de Wilson):** si los intervalos de dos condiciones apenas se solapan, la diferencia probablemente no es azar. La forma correcta de comparar es `comparaciones.csv`: diferencias pareadas por tarjeta. Si `ic_excluye_cero` es `True`, la diferencia es consistente.
- **Infracciones:** separa las automáticas (comprobables) de las semánticas (opinión del vigilante). Si las semánticas dominan, revisa unas cuantas a mano en `registros.jsonl`: los vigilantes pequeños dan falsos positivos.
- **Intentos medios:** se calculan solo sobre turnos acertados. Si hay pocos aciertos, el valor es poco fiable.
- **Tiempo:** depende del hardware y de la carga del equipo. Compara solo resultados obtenidos en la misma máquina.
- Las conclusiones valen **para esos modelos, ese mazo y esos prompts**. Consulta las limitaciones en `docs/MEMORIA.md`.

## 10. Estructura

```
tabu_local/
├── main.py                 CLI, menú y modo demo
├── config.py / config.json Configuración
├── models/                 ollama_client.py, model_manager.py, fake_client.py (pruebas)
├── game/                   game_engine.py, turn_manager.py, referee.py, roles.py,
│                           prompts.py, scoring.py, records.py, game_logger.py
├── detection/              text_normalizer.py, forbidden_checker.py, semantic_judge.py, json_utils.py
├── cards/                  cards.json (52 tarjetas), deck.py, card_validator.py, card_generator.py
├── experiment/             experiment_runner.py, metrics.py, plots.py
├── ui/console.py           Presentación en consola
├── gui/                    Interfaz gráfica: server.py (servidor local) y static/index.html
├── data/games/             Partidas (JSON)
├── data/results/           Experimentos (CSV, JSONL, PNG)
├── tests/                  Pruebas automáticas
└── docs/                   MEMORIA.md, FASES.md
```

## 11. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `Ollama no responde` | Abre la app o ejecuta `ollama serve` |
| `El modelo 'x' no está instalado` | `ollama pull x` |
| Cada paso tarda más de un minuto y `ollama ps` solo muestra **un** modelo cargado | La GPU es pequeña y Ollama descarga un modelo para cargar otro en cada turno. Deja `"num_gpu": 0` en `config.json` (opción por defecto): todo va en CPU y los tres modelos se quedan a la vez en la RAM |
| Muchos *timeouts* | Sube `ollama.timeout_s` o usa modelos más pequeños. La primera llamada a cada modelo es lenta porque lo carga en memoria |
| El vigilante marca casi todo | Las sospechas sin pruebas (cita que no está en el texto) ya se descartan solas. Si aun así marca demasiado, sube `umbral_confianza_vigilante`, usa `vigilante_modo: "consultivo"` o un modelo mayor |
| Tildes raras en Windows | Ejecuta `chcp 65001` o usa Windows Terminal; para quitar los colores, define `NO_COLOR=1` |
