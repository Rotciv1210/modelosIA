"""Prompts de cada rol.

Cada función recibe SOLO la información que corresponde a su rol, de modo que
es imposible (por construcción) que un rol vea datos de otro:

  * descriptor : palabra secreta + prohibidas + sus pistas previas + fallos del adivinador
  * adivinador : pistas + sus respuestas fallidas (nunca la secreta ni las prohibidas)
  * vigilante  : descripción + secreta + prohibidas (nunca equipos, marcador ni respuestas)

La etiqueta "ROL: ..." al inicio del prompt de sistema es solo para identificar
el rol en los registros y en el cliente simulado.
"""
from __future__ import annotations

Mensajes = list[dict[str, str]]


# ----------------------------------------------------------------- descriptor
def mensajes_descriptor(secreta: str, prohibidas: list[str], pistas_previas: list[str],
                        respuestas_fallidas: list[str], max_palabras: int,
                        estricto: bool = False) -> Mensajes:
    sistema = (
        "ROL: DESCRIPTOR\n"
        "Juegas al Tabú en español. Tu misión es que otro jugador adivine la PALABRA SECRETA "
        "a partir de tu descripción.\n"
        "Reglas obligatorias:\n"
        "1. No escribas la palabra secreta, ni partes de ella, ni plurales, diminutivos, "
        "derivados o traducciones a otros idiomas.\n"
        "2. No escribas ninguna PALABRA PROHIBIDA, ni sus plurales, derivados o traducciones.\n"
        "3. No deletrees, no digas por qué letra empieza, cuántas letras tiene ni con qué rima.\n"
        f"4. Escribe una o dos frases cortas y naturales: unas {max(10, (max_palabras * 2) // 3)} palabras "
        f"y nunca más de {max_palabras}. Termina siempre la frase.\n"
        "5. Responde SOLO con la descripción: sin comillas, sin títulos, sin explicar las reglas "
        "y sin mencionar tu papel en el juego."
    )
    usuario = [f"PALABRA SECRETA: {secreta}", f"PALABRAS PROHIBIDAS: {', '.join(prohibidas)}"]
    if pistas_previas:
        usuario.append("Tus pistas anteriores:\n" + "\n".join(f"- {p}" for p in pistas_previas))
    if respuestas_fallidas:
        usuario.append("El adivinador ha respondido (incorrecto): " + ", ".join(respuestas_fallidas))
        usuario.append("Escribe UNA pista nueva, distinta de las anteriores, que ayude a corregir el error.")
    else:
        usuario.append("Escribe tu descripción.")
    if estricto:
        usuario.append("ATENCIÓN: tu respuesta anterior no era válida (vacía, repetida, demasiado "
                       "larga o hablaba de las reglas). Escribe solo la descripción.")
    return [{"role": "system", "content": sistema}, {"role": "user", "content": "\n\n".join(usuario)}]


# ----------------------------------------------------------------- adivinador
def mensajes_adivinador(pistas: list[str], respuestas_fallidas: list[str], intento: int,
                        max_intentos: int, insistir_distinta: bool = False) -> Mensajes:
    sistema = (
        "ROL: ADIVINADOR\n"
        "Juegas al Tabú en español. Recibirás pistas que describen una palabra o expresión "
        "y debes adivinar cuál es.\n"
        'Responde ÚNICAMENTE con un objeto JSON con este formato: {"respuesta": "palabra"}\n'
        "La respuesta debe ser una sola palabra (o una expresión muy corta) en español, sin artículo."
    )
    usuario = ["PISTAS:\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pistas, 1))]
    if respuestas_fallidas:
        usuario.append("Respuestas que ya se han comprobado como INCORRECTAS (no las repitas): "
                       + ", ".join(respuestas_fallidas))
    if insistir_distinta:
        usuario.append("Tu respuesta anterior no era válida o estaba repetida. Da una palabra DIFERENTE.")
    usuario.append(f"Intento {intento} de {max_intentos}. ¿Cuál es la palabra?")
    return [{"role": "system", "content": sistema}, {"role": "user", "content": "\n\n".join(usuario)}]


# ------------------------------------------------------------------ vigilante
TIPOS_SEMANTICOS = ("ninguna", "revelacion_directa", "sinonimo_evidente", "traduccion",
                    "derivado", "deformacion", "pista_letras", "otra")


def mensajes_vigilante(descripcion: str, secreta: str, prohibidas: list[str],
                       estricto: bool = False) -> Mensajes:
    sistema = (
        "ROL: VIGILANTE\n"
        "Eres el árbitro imparcial de un juego de Tabú en español. Debes decidir si una "
        "DESCRIPCIÓN incumple las reglas. Hay infracción si la descripción:\n"
        "- revela la palabra secreta de forma directa (la nombra, la deforma con faltas de "
        "ortografía, la parte en trozos o da un sinónimo prácticamente idéntico);\n"
        "- usa la palabra secreta o una prohibida traducida a otro idioma;\n"
        "- usa un derivado claro de la palabra secreta o de una prohibida;\n"
        "- da pistas sobre letras, número de letras o rimas.\n"
        "Solo hay infracción si puedes señalar el fragmento exacto de la descripción que la "
        "provoca. NO es infracción describir la función, la forma, el uso, el lugar o el contexto: "
        "eso es exactamente lo que se pide. Ante la duda, NO hay infracción.\n"
        "Responde SOLO con un objeto JSON con estas claves:\n"
        '{"infraccion": true/false, "palabra_detectada": "fragmento COPIADO LITERALMENTE de la '
        'descripción que constituye la trampa, o null", '
        f'"tipo_infraccion": uno de {list(TIPOS_SEMANTICOS)}, '
        '"justificacion": "frase breve", "nivel_confianza": número entre 0 y 1}'
    )
    usuario = (f"PALABRA SECRETA: {secreta}\n"
               f"PALABRAS PROHIBIDAS: {', '.join(prohibidas)}\n"
               f"DESCRIPCIÓN A EVALUAR: \"{descripcion}\"")
    if estricto:
        usuario += "\n\nTu respuesta anterior no era JSON válido. Responde solo con el objeto JSON."
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


# ------------------------------------------------------- generador de tarjetas
def mensajes_generador_tarjeta(categoria: str, dificultad: str, evitar: list[str]) -> Mensajes:
    sistema = (
        "ROL: GENERADOR\n"
        "Creas tarjetas para el juego Tabú en español. Una tarjeta tiene una palabra secreta "
        "conocida por todo el mundo y siete palabras prohibidas: las siete palabras que más "
        "ayudarían a describirla, ordenadas de más a menos relevante. Las prohibidas no pueden "
        "ser la propia palabra secreta ni un plural o derivado de ella.\n"
        "Responde SOLO con JSON: "
        '{"secreta": "...", "prohibidas": ["...", "...", "...", "...", "...", "...", "..."], '
        '"variantes": ["traducción al inglés", "traducción al catalán"]}'
    )
    usuario = (f"Categoría: {categoria}\nDificultad: {dificultad}\n"
               f"No uses ninguna de estas palabras secretas: {', '.join(evitar[:80])}")
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def mensajes_revision_tarjeta(secreta: str, prohibidas: list[str]) -> Mensajes:
    sistema = (
        "ROL: REVISOR\n"
        "Evalúas tarjetas de Tabú en español. Para cada palabra prohibida indica si es "
        "relevante, es decir, si sería una pista natural para describir la palabra secreta.\n"
        'Responde SOLO con JSON: {"conocida": true/false, "relevancia": {"palabra": número 0-1, ...}}'
    )
    usuario = f"Palabra secreta: {secreta}\nPalabras prohibidas: {', '.join(prohibidas)}"
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
