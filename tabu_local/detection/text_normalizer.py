"""Normalización de texto en español.

Funciones puras (sin estado) que usan el detector de palabras prohibidas, el
validador de tarjetas y el árbitro para comparar palabras de forma robusta:
mayúsculas, tildes, puntuación, plurales, género y diminutivos.
"""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset("""
a al algo alguien algun alguna algunas alguno algunos ante antes aquel aquella aquello
asi como con contra cual cuando de del desde donde dos e el ella ellas ello ellos en entre
era eres es esa esas ese eso esos esta estas este esto estos fue ha hay la las le les lo los
mas me mi mis mucho muy ni no nos o os otra otro otros para pero poco por porque que quien
se sea ser si sin sobre son su sus tambien te tiene tu tus un una uno unos unas y ya yo
""".split())

ARTICULOS = frozenset({"el", "la", "los", "las", "un", "una", "unos", "unas", "lo"})

_NO_ALFANUM = re.compile(r"[^\w\s]|_", re.UNICODE)
_ESPACIOS = re.compile(r"\s+")

# Sufijos de diminutivo/aumentativo frecuentes en español
SUFIJOS_APRECIATIVOS = ("ito", "ita", "illo", "illa", "ico", "ica", "in", "ina", "on", "ona",
                        "ote", "ota", "azo", "aza", "ecito", "ecita", "cito", "cita")


def quitar_tildes(texto: str) -> str:
    """'Canción' -> 'Cancion', 'pingüino' -> 'pinguino', 'año' -> 'ano'."""
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, signos de puntuación sustituidos por espacios."""
    if not texto:
        return ""
    t = quitar_tildes(texto.lower())
    t = _NO_ALFANUM.sub(" ", t)
    return _ESPACIOS.sub(" ", t).strip()


def tokenizar(texto: str | None) -> list[str]:
    return normalizar(texto).split()


def quitar_articulos(texto: str) -> str:
    """Quita artículos iniciales: 'el perro' -> 'perro'."""
    tokens = normalizar(texto).split()
    while tokens and tokens[0] in ARTICULOS and len(tokens) > 1:
        tokens = tokens[1:]
    return " ".join(tokens)


def formas_plurales(palabra: str) -> set[str]:
    """Singular y plurales regulares de una palabra ya normalizada."""
    p = normalizar(palabra)
    if not p:
        return set()
    formas = {p}
    if p.endswith("z"):
        formas.add(p[:-1] + "ces")              # lápiz -> lápices
    elif p[-1] in "aeiou":
        formas.update({p + "s", p + "es"})       # casa -> casas, jabalí -> jabalíes
    else:
        formas.update({p + "es", p + "s"})       # canción -> canciones, club -> clubs
    # Si la palabra ya está en plural, añadimos el singular probable
    if p.endswith("ces") and len(p) > 4:
        formas.add(p[:-3] + "z")
    elif p.endswith("es") and len(p) > 4:
        formas.update({p[:-2], p[:-1]})
    elif p.endswith("s") and len(p) > 3:
        formas.add(p[:-1])
    return formas


def base_lexica(palabra: str) -> str:
    """Raíz aproximada: quita la vocal final ('perro' -> 'perr') o la terminación
    de infinitivo ('ladrar' -> 'ladr')."""
    p = normalizar(palabra)
    if es_infinitivo(p):
        return p[:-2]
    if len(p) > 3 and p[-1] in "aeo":
        return p[:-1]
    return p


def es_infinitivo(palabra: str) -> bool:
    p = normalizar(palabra)
    return len(p) > 4 and " " not in p and p[-2:] in ("ar", "er", "ir")


def formas_flexivas(palabra: str) -> set[str]:
    """Plurales + cambio de género + diminutivos/aumentativos regulares."""
    p = normalizar(palabra)
    if not p or " " in p:
        return {p} if p else set()
    formas = formas_plurales(p)
    base = base_lexica(p)
    if p.endswith("o"):
        formas |= formas_plurales(base + "a")   # perro -> perra
    elif p.endswith("a"):
        formas |= formas_plurales(base + "o")   # gata -> gato
    if len(base) >= 3:
        for suf in SUFIJOS_APRECIATIVOS:
            formas |= formas_plurales(base + suf)
    return formas


def es_misma_palabra(a: str, b: str) -> bool:
    """Igualdad tolerante a tildes, mayúsculas, plural y espacios internos.

    Se usa para decidir si la respuesta del adivinador es correcta: 'Perros'
    acierta 'perro', 'arco iris' acierta 'arcoíris'. No acepta cambio de género
    ni diminutivos.
    """
    na, nb = quitar_articulos(a), quitar_articulos(b)
    if not na or not nb:
        return False
    if na == nb or na.replace(" ", "") == nb.replace(" ", ""):
        return True
    if " " not in na and " " not in nb:
        return na in formas_plurales(nb) or nb in formas_plurales(na)
    # expresiones de varias palabras: comparar la última en plural/singular
    pa, pb = na.split(), nb.split()
    if len(pa) == len(pb) and pa[:-1] == pb[:-1]:
        return pa[-1] in formas_plurales(pb[-1])
    return False
