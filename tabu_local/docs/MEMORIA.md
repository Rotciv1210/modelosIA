# Memoria de la práctica: Tabú entre modelos locales

## 1. Introducción y objetivos

El objetivo es construir un juego de Tabú en el que los tres papeles los hacen modelos de lenguaje de pesos abiertos ejecutados en local con Ollama:

- El **descriptor** describe la palabra secreta sin usar la propia palabra ni las prohibidas.
- El **adivinador** intenta acertarla.
- El **vigilante** busca trampas.

Un programa en Python hace de **árbitro**: decide qué información recibe cada modelo, aplica las reglas, puntúa y registra todo.

Objetivos concretos:

1. Un juego funcional, robusto ante respuestas defectuosas de los modelos y configurable sin tocar el código.
2. Un sistema híbrido de detección de trampas: reglas deterministas más un juez semántico.
3. Un mazo de tarjetas en español validado automáticamente.
4. Un experimento reproducible: *¿cómo afecta el número de palabras prohibidas (3, 5, 7) al rendimiento?*

## 2. Diseño y arquitectura

```
                 ┌──────────────── ÁRBITRO (Python, determinista) ────────────────┐
 Mazo ──tarjeta──►  GestorTurno ──secreta+prohibidas──► DESCRIPTOR (modelo A)     │
                 │      │◄──────────── pista ──────────────┘                      │
                 │      ├─ limpiar/validar (vacía, repetida, larga, meta-rol)     │
                 │      ├─ ForbiddenChecker (reglas) ──┐                          │
                 │      ├─ VIGILANTE (modelo C) ◄──────┘ solo si las reglas pasan │
                 │      │   └─ JSON validado + umbral de confianza                │
                 │      ├─ si hay infracción → penalización, la pista se anula    │
                 │      └─ pistas válidas ──► ADIVINADOR (modelo B) ─► respuesta  │
                 │  Marcador · RegistroPartida (JSON) · eventos → consola         │
                 └────────────────────────────────────────────────────────────────┘
```

| Módulo | Responsabilidad |
|---|---|
| `models/` | Cliente HTTP de Ollama (`/api/chat`, `/api/tags`), errores tipados, gestión y verificación de modelos, clientes falsos para pruebas |
| `game/` | Prompts por rol, roles, árbitro, gestor de turno, motor de partida, puntuación, registros |
| `detection/` | Normalización del español, detector de palabras prohibidas, vigilante semántico, extracción robusta de JSON |
| `cards/` | Modelo de tarjeta, mazo sin repetición, validador, generador con revisión |
| `experiment/` | Ejecución del experimento, métricas y gráficos |
| `ui/` | Presentación en consola (observador de eventos) |

Principios de diseño:

1. **Los modelos nunca deciden el resultado.** Producen texto; el árbitro decide.
2. **El aislamiento de información se garantiza en la firma de los métodos.** `Adivinador.adivinar()` no tiene ningún parámetro por el que pueda llegarle la palabra secreta. Hay además una prueba automática que revisa todos los prompts del adivinador.
3. **Nada bloquea la partida.** Cada llamada tiene *timeout*, los errores se registran y solo se aborta si Ollama cae o falta un modelo. Incluso entonces se guarda el registro parcial.
4. **Configuración en JSON**, no en el código.
5. **Solo inferencia local.** Se rechazan hosts no locales y modelos `*-cloud`.

## 3. Decisiones tomadas para cada rol

**Descriptor.**
- Recibe la secreta, las prohibidas, sus pistas anteriores y los fallos del adivinador. Esto le permite reorientar la pista: si el adivinador dijo «lobo», la siguiente pista lo corrige.
- El prompt prohíbe expresamente plurales, derivados, traducciones, deletreos y pistas de letras, y pide solo la descripción.
- Las prompts se construyen desde cero en cada llamada, sin historial de chat. Así cada llamada es reproducible con su semilla.
- Si la respuesta es inválida (vacía, de menos de 2 palabras, repetida, o habla de las reglas o de su rol, por ejemplo «la palabra secreta es…» o «lo siento, no puedo…»), se reintenta con un prompt más estricto hasta `reintentos_respuesta_invalida` veces.
- El prompt pide unas 25 palabras con un máximo de 40. Si se pasa, el árbitro recorta por la última frase completa (nunca a mitad de frase) y registra un aviso.

**Adivinador.**
- Solo recibe las pistas válidas, sus respuestas incorrectas y el número de intento.
- Responde en JSON (`format: "json"` de Ollama), pero el árbitro también acepta texto libre: «Creo que es: el perro» → «perro».
- Si repite una respuesta fallida o no da una respuesta válida, se le pide otra.
- Un acierto admite variaciones de mayúsculas, tildes, plural, artículos y espacios («arco iris» = «arcoíris»). No admite cambios de género ni diminutivos.

**Vigilante.**
- Solo recibe la descripción, la secreta y las prohibidas. No conoce los equipos, el marcador ni las respuestas, así que no puede favorecer a nadie.
- Trabaja con temperatura 0 y debe devolver un JSON con `infraccion`, `palabra_detectada`, `tipo_infraccion`, `justificacion` y `nivel_confianza`. El árbitro valida ese esquema: normaliza tipos y porcentajes, y descarta cualquier campo inventado.
- Solo se le consulta cuando las reglas no han encontrado nada. Esto ahorra tiempo y evita sumar dos veces la misma trampa.
- Su veredicto solo penaliza si la confianza alcanza el umbral (0,8 por defecto). En modo `consultivo` solo se registra.
- **Tiene que aportar pruebas.** Debe citar literalmente el fragmento de la descripción que constituye la trampa. Si el fragmento citado no aparece en el texto, el árbitro descarta la sospecha y no penaliza; queda registrada como `descartado_por_arbitro`. Se añadió tras observar en una partida real que `gemma2:2b` afirmaba que una descripción de «cumpleaños» contenía esa palabra cuando no era así.
- Si no responde con JSON válido tras un reintento, no penaliza (beneficio de la duda), pero el fallo queda registrado.
- Si el vigilante es el mismo modelo que un descriptor, el programa avisa del posible sesgo.

**Turnos y equipos.**
- Cada equipo es un par descriptor-adivinador, y el vigilante es común.
- En cada ronda juega un turno cada equipo y cada turno usa una tarjeta nueva (el mazo nunca repite tarjeta en la sesión).
- Por defecto, una infracción termina el turno, como en el Tabú real. Es configurable.

## 4. Detección de palabras prohibidas

### 4.1 Detección automática (Python, determinista)

Se normaliza el texto: minúsculas, sin tildes, signos de puntuación convertidos en espacios. Después, para la secreta y cada prohibida, se busca:

| Tipo | Ejemplo detectado | Cómo |
|---|---|---|
| exacta | «perro» | token igual |
| morfológica | «perros», «perra», «perrito», «lápices» | conjunto generado de plurales, género, diminutivos y aumentativos |
| derivada | «perrera» (perro), «ladrador» / «ladra» (ladrar) | prefijo común con la raíz (≥ 4 letras); los verbos usan la raíz sin -ar/-er/-ir |
| compuesta | «paraguas» contiene «agua» | el objetivo (≥ 4 letras) aparece dentro de otra palabra, no al principio |
| frase | «echar de menos» | expresión de varias palabras, incluido su plural |
| deletreo | «p-e-r-r-o», «P E R R O» | secuencias de letras sueltas |
| traducción | «dog», «gos», «chien» | variantes registradas en la tarjeta (campo `variantes`) o en un diccionario global |

Reglas de recuento:

- Cada palabra objetivo cuenta como mucho una infracción («perro perros» = 1).
- Un mismo fragmento del texto solo penaliza una vez. Por ejemplo, «helicóptero» es la secreta y además deriva de «hélice», pero cuenta como una sola infracción.
- Las variantes que coinciden con palabras vacías del español se ignoran para evitar falsos positivos (por ejemplo, el catalán «son» frente al español «son»).

### 4.2 Detección semántica (vigilante)

Se encarga de lo que las reglas no pueden ver:

- sinónimos evidentes («can» por «perro»);
- traducciones no registradas;
- faltas de ortografía intencionadas («pero» por «perro»);
- pistas sobre letras o rimas («empieza por p», «rima con cerro»);
- perífrasis que revelan la palabra directamente.

### 4.3 Qué queda a interpretación

Las reglas son objetivas y reproducibles, pero tienen límites:

- La raíz es aproximada. Hay falsos positivos raros, como «libres» para «libro», y falsos negativos con raíces cortas o irregulares: «nevar» no se detecta para «nieve», ni «panecillo» para «pan».
- La frontera entre «buena pista» y «sinónimo demasiado evidente» es subjetiva. Por eso el vigilante devuelve una confianza y el árbitro aplica un umbral.
- Los vigilantes pequeños tienen sesgos conocidos: marcan de más o se dejan convencer. En el CSV se guardan por separado las infracciones automáticas y las semánticas, para poder analizar ambas.

## 5. Generación y validación de tarjetas

**Mazo base.** `cards/cards.json` tiene 52 tarjetas escritas a mano, en 14 categorías y 3 dificultades. Cada tarjeta tiene:

- 5 prohibidas principales (dentro del rango 3–5 que pide el enunciado), ordenadas de más a menos relevante;
- 2 prohibidas extra, que solo usa la condición experimental de 7;
- traducciones de la palabra secreta.

**Validador.** Rechaza una tarjeta si:

- faltan campos o los tipos son incorrectos;
- tiene menos de 3 o más de 5 prohibidas principales, o más de 7 en total;
- repite prohibidas;
- alguna prohibida es la propia secreta o una forma flexionada de ella;
- alguna prohibida es una palabra vacía;
- la categoría o la dificultad no son válidas.

Avisa, sin rechazar, de prohibidas que son derivados redundantes y de variantes inútiles. A nivel de mazo, rechaza IDs repetidos y secretas repetidas, también en plural.

**Generador.**
1. Un modelo local propone tarjetas en JSON.
2. Pasan por el validador y por un control de duplicados frente al mazo.
3. Opcionalmente, un modelo revisor puntúa la relevancia de cada prohibida y descarta las que están por debajo de 0,4.
4. Las aceptadas se guardan en `cards_generadas.json`, separadas del mazo base, para que el experimento use siempre tarjetas revisadas.

## 6. Diseño experimental

- **Pregunta:** ¿cómo afecta el número de palabras prohibidas al rendimiento?
- **Variable independiente:** número de prohibidas. Condición A = 3, B = 5, C = 7.
  - Las condiciones son **anidadas**: las 3 de A están dentro de las 5 de B, y estas dentro de las 7 de C. Así solo cambia la cantidad de restricciones, no qué palabras se prohíben.
- **Diseño intra-sujetos:**
  - Las mismas tarjetas (por defecto 30, con selección fija por semilla), los mismos equipos, el mismo vigilante y la misma configuración en las tres condiciones.
  - La misma **semilla de muestreo** por (repetición, tarjeta, equipo) en las tres condiciones.
- **Control de orden:** para cada (repetición, tarjeta, equipo) se juegan las tres condiciones seguidas, en orden aleatorio con semilla. Así no se confunden con la condición posibles derivas del sistema (caché, temperatura del equipo, otros procesos).
- **Repeticiones:** 2 por defecto, con semillas distintas, para estimar la variabilidad del muestreo.
- **Variables dependientes:**
  - % de acierto;
  - infracciones por turno (automáticas y semánticas por separado);
  - descripciones inválidas;
  - tiempo medio de respuesta del descriptor y del adivinador;
  - intentos necesarios (solo en turnos acertados);
  - puntuación media por ronda (= por turno).
- **Análisis:**
  - medias con desviación típica e IQR;
  - IC 95 %: de Wilson para proporciones y bootstrap para medias;
  - **diferencias pareadas** entre condiciones (mismo turno en dos condiciones) con IC 95 % bootstrap.
  - El análisis pareado elimina la variabilidad debida a la dificultad de cada tarjeta.
- **Hipótesis a contrastar:** más prohibidas → más infracciones y menos aciertos. Es una hipótesis, no un resultado.

## 7. Resultados obtenidos

**Pendientes de ejecución.** El código se ha desarrollado y probado en un entorno sin Ollama ni modelos descargados, con clientes simulados que no son modelos de lenguaje. Por eso no se incluye ningún resultado experimental. Para obtenerlos:

```bash
python main.py experimento
```

Después, rellenad esta tabla con `data/results/<id>/resumen_condiciones.csv` y añadid los gráficos de `graficos/`:

| Condición | n turnos | % acierto [IC 95 %] | Infracciones/turno (DT) | Inválidas/turno | Intentos (aciertos) | Puntuación/ronda (DT) | t. descriptor (s) |
|---|---|---|---|---|---|---|---|
| A (3) | | | | | | | |
| B (5) | | | | | | | |
| C (7) | | | | | | | |

## 8. Análisis y discusión

Pendiente de los resultados. Guion para redactarlo:

1. ¿Bajan los aciertos al pasar de 3 a 5 y de 5 a 7? Mirad `comparaciones.csv`, métrica `acierto`.
2. ¿Bajan porque aumentan las infracciones o porque las pistas son peores sin que haya trampas? Comparad las infracciones con los aciertos en los turnos sin infracción.
3. ¿Se comportan igual todos los equipos (`resumen_equipos.csv`) y todas las dificultades?
4. Revisad a mano una muestra de infracciones semánticas para estimar la precisión del vigilante.
5. ¿Cambia el tiempo de respuesta con la longitud del prompt?

## 9. Limitaciones

- **Validez externa limitada:** los resultados dependen de los modelos, del tamaño de cuantización, de los prompts y del mazo concreto. Un cambio en cualquiera de ellos puede alterar las conclusiones.
- **Tamaño muestral:** 30 tarjetas × 2 equipos × 2 repeticiones = 120 turnos por condición. Bastan para detectar efectos grandes (unos 15–20 puntos en % de acierto), no efectos pequeños.
- **Determinismo parcial:** la semilla fija el muestreo, pero Ollama puede dar salidas distintas en otro hardware o versión. Los tiempos dependen totalmente de la máquina.
- **Detector automático:** el español tiene morfología irregular. La raíz aproximada produce falsos positivos y negativos raros, ya documentados en las pruebas.
- **Vigilante:** un modelo pequeño como juez es ruidoso. Sus errores afectan a las infracciones semánticas y, por tanto, a la puntuación. Para mitigarlo hay un umbral, el modo consultivo y un registro separado.
- **Prohibidas extra:** las de las posiciones 6 y 7 se eligieron a mano como menos relevantes. Su efecto puede ser menor que el de las 5 primeras, lo que forma parte de lo que se mide.
- **Sesgo de corpus:** palabras muy frecuentes en los datos de entrenamiento pueden ser más fáciles para los modelos, sin relación con su dificultad para un humano.
- **Sin pruebas de significación formales:** se usan intervalos de confianza. Un análisis más completo podría usar una regresión logística de efectos mixtos con la tarjeta como efecto aleatorio.

## 10. Conclusiones

El proyecto ofrece un entorno completo y reproducible para jugar al Tabú entre modelos locales:

- un árbitro determinista que aísla la información de cada rol;
- una detección de trampas en dos capas, con criterios explícitos sobre qué es objetivo y qué es interpretable;
- un mazo validado y un generador con revisión;
- registros completos en JSON;
- un experimento intra-sujetos con condiciones anidadas, análisis pareado y gráficos;
- 87 pruebas automáticas que no necesitan Ollama;
- una interfaz gráfica en el navegador para la demostración en clase.

La conclusión sobre el efecto del número de palabras prohibidas queda pendiente de ejecutar el experimento con modelos reales.
