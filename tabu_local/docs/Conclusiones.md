# Conclusiones de los primeros experimentos

**Proyecto:** Tabú entre modelos locales
**Pregunta:** ¿cómo afecta el número de palabras prohibidas (3, 5 o 7) al rendimiento de los modelos?

Se han hecho dos ejecuciones, las dos en el mismo portátil (Windows, 16 GB de RAM, modelos solo en CPU) y con los mismos modelos:

| Equipo | Describe | Adivina |
|---|---|---|
| Azul | `llama3.2:3b` | `qwen2.5:3b` |
| Rojo | `qwen2.5:3b` | `llama3.2:3b` |
| Vigilante (común) | `gemma2:2b` | — |

| Ejecución | Identificador | Tarjetas × equipos × condiciones × repeticiones | Turnos | Duración |
|---|---|---|---|---|
| Prueba piloto | `exp_20261106_112159` | 5 × 2 × 3 × 1 | 30 | ~11 min |
| Experimento completo | `exp_20261106_114534` | 30 × 2 × 3 × 2 | 360 | ~2 h |

---

## 1. Prueba piloto (30 turnos)

La prueba piloto servía para comprobar que todo funcionaba y para estimar cuánto tardaría el experimento completo. Sus cifras **no son concluyentes** (solo 10 turnos por condición), pero ya señalaron los problemas que después confirmó el experimento completo.

| Condición | % acierto | Infracciones/turno | Puntuación/turno |
|---|---|---|---|
| 3 prohibidas | 50 % | 0,70 | −0,20 |
| 5 prohibidas | 20 % | 1,00 | −0,80 |
| 7 prohibidas | 10 % | 1,10 | −1,00 |

**Conclusiones de la prueba piloto:**

1. **El sistema funciona de principio a fin con modelos reales:** precarga, turnos, detección de trampas, registro, estadística y gráficos.
2. **Hubo un primer indicio del efecto:** el acierto bajó al aumentar las prohibidas, sobre todo en el Equipo Azul (100 % → 40 % → 20 %).
3. **El Equipo Rojo no acertó ninguna tarjeta.** `qwen2.5:3b` como descriptor escribía la palabra secreta tal cual («Un helicóptero tiene dos hélices…»).
4. **El vigilante no era fiable.** Dio 27 veredictos y en todos dijo «infracción», con una confianza de 0,9 o 1,0. El árbitro descartó 22 por falta de pruebas, y las 5 que llegaron a penalizar resultaron ser falsos positivos.
5. **Decisión que se tomó:** usar el vigilante en modo `consultivo` en el experimento completo. Más tarde se vio que el cambio no llegó a aplicarse; ver el apartado 2.4.

---

## 2. Experimento completo (360 turnos)

### 2.1 El efecto existe para la diferencia grande

| Condición | % acierto [IC 95 %] | Infracciones/turno | Puntuación/turno |
|---|---|---|---|
| 3 prohibidas | **27,5 %** [20,3–36,1] | 0,82 | −0,54 |
| 5 prohibidas | **20,8 %** [14,5–29,0] | 0,92 | −0,71 |
| 7 prohibidas | **15,0 %** [9,7–22,5] | 1,09 | −0,94 |

- Al pasar de 3 a 7 prohibidas, el acierto cae **12,5 puntos**. La diferencia es significativa (McNemar exacto, **p = 0,008**, 120 pares): 22 tarjetas se acertaron con 3 prohibidas y se fallaron con 7, frente a solo 7 en sentido contrario.
- Los pasos de 3 a 5 (p = 0,20) y de 5 a 7 (p = 0,25) van en la misma dirección, pero con esta muestra no se distinguen del azar.
- La puntuación y las infracciones empeoran de forma parecida. La diferencia de 3 a 7 es significativa en las dos métricas, y la de 5 a 7 también.

**Conclusión:** ampliar la lista de prohibidas empeora el rendimiento. Con 120 pares se detecta el efecto grande (de 3 a 7), pero no los pasos intermedios.

### 2.2 El empeoramiento llega por dos vías

**a) Más trampas involuntarias.** Los turnos en que el descriptor usa una palabra prohibida aumentan con el tamaño de la lista. En cambio, los turnos en que escribe la palabra secreta no cambian, porque la secreta está prohibida en todas las condiciones.

| Condición | Turnos con una palabra prohibida | Turnos con la palabra secreta |
|---|---|---|
| 3 | 36 | 50 |
| 5 | 42 | 53 |
| 7 | 63 | 48 |

**b) Pistas peores, aunque no haya trampa.** En el Equipo Azul, si solo se cuentan los turnos sin infracciones, el acierto también baja:

| Condición | Turnos limpios | % acierto |
|---|---|---|
| 3 | 33 | 87,9 % |
| 5 | 31 | 64,5 % |
| 7 | 28 | 60,7 % |

**Conclusión:** prohibir más palabras lleva a los modelos a usar alguna sin querer y, cuando no lo hacen, les deja peores palabras con las que describir.

Además, las palabras prohibidas más relevantes son las que más se usan. Por posición en la lista, las infracciones fueron 61, 46, 19, 20, 8, 8 y 7. Las palabras 6 y 7 casi no se usaron, y eso explica que el paso de 5 a 7 tenga poco efecto.

### 2.3 El modelo descriptor pesa más que la regla

| Condición | Azul: % acierto | Rojo: % acierto |
|---|---|---|
| 3 | 48,3 % | 6,7 % |
| 5 | 33,3 % | 8,3 % |
| 7 | 28,3 % | 1,7 % |

- `qwen2.5:3b`, como descriptor, escribió la palabra secreta en el **64 %** de sus turnos (116 de 180). `llama3.2:3b` lo hizo en el **19 %** (35 de 180).
- La diferencia entre equipos es mucho mayor que la diferencia entre condiciones. Por eso el efecto del número de prohibidas se ve, sobre todo, en el Equipo Azul.

**Conclusión:** la primera regla del juego, no decir la palabra, es la que más diferencia a los modelos. Elegir el descriptor importa más que el tamaño de la lista.

### 2.4 Un modelo de 2 B no sirve como juez

El experimento se ejecutó con el vigilante en modo `penaliza`: el cambio a `consultivo` no llegó a aplicarse.

| Dato | Valor |
|---|---|
| Veredictos emitidos | 269 (todos con JSON válido) |
| Acusaciones de infracción | 196 (**73 %**) |
| Acusaciones descartadas por el árbitro (la cita no estaba en la pista) | 177 (**90 %** de las acusaciones) |
| Penalizaciones aplicadas | 19 (5,6 % de todas las infracciones) |
| Penalizaciones defendibles tras la revisión manual | 1 («La primera sílaba es "qui-"», en la tarjeta *médico*) |

- **Sin la regla que obliga a aportar pruebas**, el vigilante habría penalizado unas 196 veces en lugar de 19, y el experimento habría medido sobre todo el ruido del juez.
- **Análisis de sensibilidad:** al quitar los 16 tríos de turnos afectados por el vigilante, el acierto queda en 28,8 %, 23,1 % y 16,3 %, y la diferencia de 3 a 7 sigue siendo significativa (p = 0,019).

**Conclusión:** el diseño híbrido funciona. Las reglas deterministas deciden lo que se puede comprobar, y el modelo solo opina, siempre con pruebas. Las penalizaciones del vigilante no cambian las conclusiones.

### 2.5 Otros resultados

- **Tiempo:** el tiempo de respuesta del descriptor no cambia con la condición (4,1, 4,5 y 4,3 s), así que un prompt algo más largo no le afecta.
- **Descripciones inválidas:** casi no hubo (5 en 360 turnos). Los mecanismos de recuperación apenas tuvieron que actuar.
- **Detector automático:** de las 320 infracciones que detectó, 248 fueron coincidencias exactas, 51 morfológicas y 21 por derivación. Los posibles falsos positivos fueron pocos («suelen» por «suelo», «marina» por «mar»).

---

## 3. Limitaciones

- Los resultados valen para estos tres modelos de 2 a 3 B, estos prompts y este mazo.
- Con 120 pares no se pueden distinguir diferencias de unos 6 puntos.
- El Equipo Rojo apenas acierta, de modo que el efecto se estima casi solo con el Equipo Azul.
- Una infracción termina el turno, lo que mezcla «hacer trampa» con «describir peor». El apartado 2.2 los separa solo en parte.
- La clasificación de las 19 penalizaciones del vigilante la hizo una sola persona.

## 4. Próximos pasos

1. **Repetir el experimento con el vigilante en modo `consultivo`**, comprobando antes que el `config.json` guardado en la carpeta de resultados lo refleja.
2. **Probar `fin_turno_por_infraccion: false`**, para separar del todo las trampas de la calidad de las pistas.
3. **Comparar las seis parejas posibles de modelos** con 5 prohibidas, para responder qué combinación describe y adivina mejor.
4. **Aumentar la muestra** a unos 300 pares si se quieren distinguir los pasos de 3 a 5 y de 5 a 7.

---

## 5. Conclusión general

> Ampliar la lista de palabras prohibidas de 3 a 7 reduce el acierto del 27,5 % al 15,0 % (p = 0,008). El motivo es doble: los modelos usan más palabras prohibidas sin querer y, cuando no lo hacen, sus pistas son menos informativas. Aun así, el factor que más pesa es el modelo descriptor: `qwen2.5:3b` revela la palabra secreta en dos de cada tres turnos. Y un modelo de 2 B no es un juez fiable sin un árbitro que le exija pruebas.

*Fuentes: `turnos.csv`, `resumen_condiciones.csv`, `resumen_equipos.csv`, `comparaciones.csv`, `mcnemar.csv`, `acierto_sin_infraccion.csv`, `auditoria_vigilante.json` y `registros.jsonl` de las carpetas `data/results/exp_20261106_112159` y `data/results/exp_20261106_114534`.*
