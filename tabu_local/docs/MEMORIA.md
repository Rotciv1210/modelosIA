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

**Ejecución.** Experimento `exp_20261106_114534`, ejecutado el 6 de noviembre de 2026 en un portátil con Windows, 16 GB de RAM y los modelos solo en CPU (`num_gpu: 0`). Se jugaron 360 turnos: 30 tarjetas × 2 equipos × 3 condiciones × 2 repeticiones, es decir, 120 turnos por condición. Duró 2 horas. El vigilante (`gemma2:2b`) estuvo en modo `penaliza`.

| Equipo | Describe | Adivina |
|---|---|---|
| Azul | `llama3.2:3b` | `qwen2.5:3b` |
| Rojo | `qwen2.5:3b` | `llama3.2:3b` |

### 7.1 Resultados por condición

| Condición | % acierto [IC 95 %] | Infracciones/turno [IC 95 %] | Inválidas/turno | Intentos (aciertos) | Puntuación/turno [IC 95 %] | t. descriptor (s) |
|---|---|---|---|---|---|---|
| A (3 prohibidas) | **27,5 %** [20,3–36,1] | 0,82 [0,69–0,94] | 0,03 | 1,39 ± 0,61 | −0,54 [−0,73, −0,34] | 4,1 ± 2,0 |
| B (5 prohibidas) | **20,8 %** [14,5–29,0] | 0,92 [0,77–1,08] | 0,00 | 1,52 ± 0,65 | −0,71 [−0,91, −0,51] | 4,5 ± 2,6 |
| C (7 prohibidas) | **15,0 %** [9,7–22,5] | 1,09 [0,94–1,26] | 0,02 | 1,17 ± 0,38 | −0,94 [−1,14, −0,75] | 4,3 ± 1,9 |

Fuente: `resumen_condiciones.csv`. Gráficos: `graficos/tasa_acierto.png`, `infracciones.png` y `puntuacion.png`.

### 7.2 Comparaciones pareadas

Cada turno se compara consigo mismo en otra condición: misma tarjeta, equipo y repetición (120 pares).

| Comparación | Δ acierto [IC 95 %] | McNemar (p) | Δ infracciones [IC 95 %] | Δ puntuación [IC 95 %] |
|---|---|---|---|---|
| 3 → 5 | −6,7 pts [−15,8, +1,7] | 0,20 | +0,10 [−0,04, +0,24] | −0,17 [−0,38, +0,03] |
| 3 → 7 | **−12,5 pts** [−20,8, −4,2] | **0,008** | **+0,28** [+0,13, +0,43] | **−0,40** [−0,60, −0,20] |
| 5 → 7 | −5,8 pts [−14,2, +2,5] | 0,25 | **+0,18** [+0,03, +0,33] | **−0,23** [−0,44, −0,04] |

En negrita, las diferencias cuyo intervalo excluye el cero. Fuentes: `comparaciones.csv` y `mcnemar.csv`. En la comparación 3 → 7 hay 22 tarjetas que se acertaron con 3 prohibidas y se fallaron con 7, frente a solo 7 en sentido contrario.

### 7.3 Resultados por equipo

| Condición | Azul: % acierto | Rojo: % acierto | Azul: infracc./turno | Rojo: infracc./turno |
|---|---|---|---|---|
| 3 | 48,3 % [36,2–60,7] | 6,7 % [2,6–15,9] | 0,50 | 1,13 |
| 5 | 33,3 % [22,7–45,9] | 8,3 % [3,6–18,1] | 0,57 | 1,27 |
| 7 | 28,3 % [18,5–40,8] | 1,7 % [0,3–8,9] | 0,63 | 1,55 |

Fuente: `resumen_equipos.csv`. Gráfico: `graficos/acierto_por_equipo.png`.

### 7.4 Origen de las infracciones

De las 339 infracciones, 320 las detectaron las reglas en Python y 19 el vigilante.

| | Equipo Azul | Equipo Rojo |
|---|---|---|
| Turnos en los que el descriptor escribió la **palabra secreta** | 35 de 180 (19 %) | **116 de 180 (64 %)** |
| Infracciones por usar una **palabra prohibida** | 62 | 107 |

| Condición | Turnos con palabra prohibida | Turnos con la palabra secreta |
|---|---|---|
| 3 | 36 | 50 |
| 5 | 42 | 53 |
| 7 | 63 | 48 |

Por tipo de detección, 248 infracciones fueron coincidencias exactas, 51 morfológicas (plurales, género, diminutivos) y 21 por derivación.

### 7.5 Acierto en los turnos sin infracción

Con esta tabla se separan los dos mecanismos posibles: hacer trampa frente a describir peor.

| Condición | Azul: turnos limpios | Azul: % acierto [IC 95 %] |
|---|---|---|
| 3 | 33 | 87,9 % [72,7–95,2] |
| 5 | 31 | 64,5 % [47,0–78,9] |
| 7 | 28 | 60,7 % [42,4–76,4] |

El Equipo Rojo tuvo muy pocos turnos limpios (6, 8 y 3), así que sus porcentajes no son interpretables. Fuente: `acierto_sin_infraccion.csv`.

### 7.6 Comportamiento del vigilante

Fuente: `auditoria_vigilante.json`.

- Emitió 269 veredictos, todos con JSON válido.
- Acusó de infracción en 196 de ellos (**73 %**), casi siempre con una confianza de 0,9 o 1,0.
- El árbitro descartó **177 de las 196 acusaciones (90 %)**, porque el fragmento citado no aparecía en la pista. Casi siempre afirmaba que la palabra secreta estaba escrita, y no lo estaba.
- Se aplicaron 19 penalizaciones semánticas. En la revisión manual, solo una es defendible: «La primera sílaba es "qui-"», en la tarjeta *médico*, que es una pista de letras. Las otras 18 son descripciones legítimas, por ejemplo «almacenar alimentos frescos» (nevera), «tiene camillas y monitores» (hospital) o «es lo que transporta a gente a otra ciudad» (tren).

**Análisis de sensibilidad.** Se repitió la comparación excluyendo los 16 tríos de turnos afectados por una penalización semántica (104 pares). El acierto queda en 28,8 %, 23,1 % y 16,3 %, y la diferencia 3 → 7 sigue siendo significativa (McNemar p = 0,019). Las penalizaciones del vigilante no cambian las conclusiones.

## 8. Análisis y discusión

**1. Más palabras prohibidas reducen el rendimiento.** El acierto baja de forma monótona: 27,5 %, 20,8 % y 15,0 %. La caída de 3 a 7 (−12,5 puntos) es estadísticamente consistente según el IC pareado y McNemar (p = 0,008). Los pasos intermedios (3 → 5 y 5 → 7) van en la misma dirección, pero con 120 pares no alcanzan a distinguirse del azar. Lo mismo ocurre con la puntuación (−0,54, −0,71, −0,94) y con las infracciones (0,82, 0,92, 1,09). La hipótesis se confirma para la diferencia grande, no para las pequeñas.

**2. El efecto llega por dos vías.**
- **Más trampas involuntarias.** Los turnos con una palabra prohibida suben de 36 a 42 y a 63. En cambio, los turnos con la palabra secreta no varían (50, 53, 48), como cabía esperar, porque la secreta está prohibida en todas las condiciones. Por tanto, el aumento de infracciones se debe a las palabras añadidas a la lista.
- **Peores descripciones, incluso sin trampas.** En el Equipo Azul, cuando el descriptor respeta las reglas, el acierto cae del 87,9 % (3 prohibidas) al 64,5 % y al 60,7 %. Al prohibir las palabras más útiles, las pistas que quedan son menos informativas.

**3. Las prohibidas más relevantes son las que más se usan.** Las infracciones por posición en la lista fueron 61, 46, 19, 20, 8, 8 y 7. Las dos primeras palabras, las más ligadas a la secreta, concentran la mayoría. Las extra (posiciones 6 y 7) apenas se usaron, lo que explica por qué el paso de 5 a 7 tiene un efecto menor.

**4. La pareja de modelos importa más que el número de prohibidas.** La diferencia entre equipos (48 % frente a 7 % con 3 prohibidas) es mucho mayor que la diferencia entre condiciones. `qwen2.5:3b` como descriptor escribió la palabra secreta en el 64 % de sus turnos («Un helicóptero tiene dos hélices…»): no respeta la regla principal del juego. Con los mismos modelos y los papeles cruzados, `llama3.2:3b` lo hace en el 19 %. Por eso el efecto de la condición se observa sobre todo en el Equipo Azul, ya que el Rojo está cerca del 0 % en todas.

**5. Un modelo pequeño no sirve como juez.** `gemma2:2b` acusó en el 73 % de los casos y, en 9 de cada 10 acusaciones, inventó la prueba. Sin la regla de exigir que el fragmento citado aparezca en la pista, habría penalizado unas 196 veces en lugar de 19, y el experimento habría medido sobre todo el ruido del juez. Es un argumento a favor del diseño híbrido: las reglas deterministas deciden lo comprobable y el modelo solo opina, siempre con pruebas.

**6. Tiempos.** El tiempo de respuesta del descriptor no cambia con la condición (4,1, 4,5 y 4,3 s): un prompt algo más largo no afecta de forma apreciable. En cambio, la duración de los turnos depende sobre todo del equipo. Los del Azul duran más porque llegan más a menudo al adivinador y al vigilante, mientras que los del Rojo suelen cortarse en la primera pista.

## 9. Limitaciones

- **Validez externa limitada:** los resultados son de estos tres modelos de 2–3 B, estos prompts y este mazo. Con modelos mayores el efecto podría ser distinto.
- **Tamaño muestral:** 120 pares por comparación permiten detectar la diferencia 3 → 7 (unos 12 puntos), pero no los pasos de 2 en 2 (unos 6 puntos). Para distinguirlos harían falta varios cientos de pares.
- **Equipos desequilibrados:** el Equipo Rojo apenas acierta, de modo que el efecto de la condición se estima casi solo con el Equipo Azul.
- **Una infracción termina el turno:** con esta regla, las trampas y las descripciones peores se entrelazan. El apartado 7.5 los separa en parte; un experimento con `fin_turno_por_infraccion: false` lo haría mejor.
- **Vigilante en modo penaliza:** 19 penalizaciones (5,6 % de las infracciones), casi todas falsas, afectaron a 16 tríos de turnos. El análisis de sensibilidad muestra que no cambian las conclusiones, pero en una repetición conviene usar el modo `consultivo`.
- **Detector automático:** en la revisión aparecieron pocos falsos positivos dudosos, como «suelen» detectado como derivado de «suelo», o «marina» de «mar».
- **Revisión manual parcial:** la clasificación de las 19 infracciones semánticas la hizo una sola persona; no se revisaron todos los veredictos.
- **Determinismo parcial:** otra máquina u otra versión de Ollama pueden dar respuestas y tiempos distintos.
- **Sin modelo estadístico completo:** se usan IC, comparaciones pareadas y McNemar. Una regresión logística de efectos mixtos, con la tarjeta y el equipo como efectos aleatorios, sería más precisa.

## 10. Conclusiones

1. **Ampliar la lista de prohibidas empeora el rendimiento:** de 3 a 7 palabras, el acierto cae del 27,5 % al 15,0 % (McNemar p = 0,008) y las infracciones suben de 0,82 a 1,09 por turno. Los pasos intermedios siguen la misma tendencia sin alcanzar significación con esta muestra.
2. **El empeoramiento llega por dos vías:** más palabras prohibidas usadas sin querer y pistas menos informativas incluso cuando se respetan las reglas. En el mejor equipo, el acierto de los turnos limpios baja del 88 % al 61 %.
3. **La elección del modelo descriptor pesa más que la regla:** `qwen2.5:3b` escribe la palabra secreta en dos de cada tres turnos, y `llama3.2:3b` en uno de cada cinco.
4. **Un modelo de 2 B no es un juez fiable:** el diseño híbrido (reglas deterministas más vigilante obligado a aportar pruebas) evitó el 90 % de sus acusaciones falsas.

Además, el proyecto ofrece un entorno completo y reproducible:
- un árbitro determinista que aísla la información de cada rol;
- una detección de trampas en dos capas;
- un mazo validado;
- registros completos;
- un experimento intra-sujetos con análisis pareado;
- 90 pruebas automáticas;
- una interfaz gráfica para la demostración en clase.
