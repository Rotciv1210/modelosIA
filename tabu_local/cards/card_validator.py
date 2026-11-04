"""Validación automática de tarjetas antes de que entren en el juego.

Comprobaciones por tarjeta (errores = la tarjeta se rechaza; avisos = se acepta
pero conviene revisarla):

  * Campos obligatorios y tipos correctos.
  * Palabra secreta de 1 a 3 palabras, con letras.
  * Entre 3 y 5 palabras prohibidas principales (+ 0-4 extra; máx. 7 en total
    para el experimento).
  * Sin prohibidas repetidas (tras normalizar).
  * Ninguna prohibida es la secreta ni una forma flexionada/derivada de ella
    (sería redundante: el detector ya la prohíbe).
  * Prohibidas sin palabras vacías ('de', 'que', ...) ni demasiado cortas.
  * Categoría y dificultad dentro de los valores admitidos.

Comprobaciones de mazo: palabras secretas no repetidas (ni en plural) e
identificadores únicos.

La relevancia semántica de las prohibidas no se puede comprobar con reglas; el
generador de tarjetas ofrece una revisión opcional con un modelo local.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from detection.text_normalizer import (STOPWORDS, base_lexica, es_misma_palabra,
                                       formas_flexivas, normalizar)

CATEGORIAS = ("animales", "comida", "objetos", "lugares", "profesiones", "naturaleza",
              "transporte", "deportes", "cuerpo", "tecnologia", "musica", "hogar",
              "eventos", "conceptos")
DIFICULTADES = ("facil", "media", "dificil")
MIN_PROHIBIDAS, MAX_PROHIBIDAS = 3, 5
MAX_EXTRA = 4
MAX_TOTAL = 7


@dataclass
class ResultadoValidacion:
    id: str
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not self.errores


def _es_lista_de_textos(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validar_tarjeta(t: dict) -> ResultadoValidacion:
    res = ResultadoValidacion(id=str(t.get("id", "?")))
    E, A = res.errores.append, res.avisos.append

    for campo in ("id", "secreta", "prohibidas", "categoria", "dificultad"):
        if campo not in t:
            E(f"Falta el campo '{campo}'")
    if res.errores:
        return res

    secreta = t["secreta"]
    if not isinstance(secreta, str) or not normalizar(secreta):
        E("La palabra secreta está vacía o no es texto")
        return res
    ns = normalizar(secreta)
    if not 1 <= len(ns.split()) <= 3:
        E("La palabra secreta debe tener entre 1 y 3 palabras")
    if not any(c.isalpha() for c in ns):
        E("La palabra secreta debe contener letras")

    prohibidas, extra = t["prohibidas"], t.get("prohibidas_extra", [])
    if not _es_lista_de_textos(prohibidas):
        E("'prohibidas' debe ser una lista de textos")
        return res
    if not _es_lista_de_textos(extra):
        E("'prohibidas_extra' debe ser una lista de textos")
        return res
    if not MIN_PROHIBIDAS <= len(prohibidas) <= MAX_PROHIBIDAS:
        E(f"Debe haber entre {MIN_PROHIBIDAS} y {MAX_PROHIBIDAS} prohibidas (hay {len(prohibidas)})")
    if len(extra) > MAX_EXTRA or len(prohibidas) + len(extra) > MAX_TOTAL:
        E(f"Demasiadas prohibidas extra (máximo {MAX_TOTAL} en total)")

    vistas: list[str] = []
    formas_secreta = formas_flexivas(ns) if " " not in ns else {ns}
    base_secreta = base_lexica(ns)
    for p in prohibidas + extra:
        np_ = normalizar(p)
        if not np_:
            E("Hay una palabra prohibida vacía")
            continue
        if any(es_misma_palabra(np_, v) for v in vistas):
            E(f"Prohibida repetida: '{p}'")
        vistas.append(np_)
        if np_ == ns or np_ in formas_secreta or es_misma_palabra(np_, ns):
            E(f"La prohibida '{p}' es la propia palabra secreta o una forma suya")
        elif len(base_secreta) >= 4 and np_.startswith(base_secreta):
            A(f"La prohibida '{p}' parece un derivado de la secreta (redundante)")
        if np_ in STOPWORDS:
            E(f"La prohibida '{p}' es una palabra vacía sin contenido")
        elif len(np_) < 2:
            E(f"La prohibida '{p}' es demasiado corta")

    if t["categoria"] not in CATEGORIAS:
        E(f"Categoría desconocida '{t['categoria']}'. Válidas: {', '.join(CATEGORIAS)}")
    if t["dificultad"] not in DIFICULTADES:
        E(f"Dificultad desconocida '{t['dificultad']}'. Válidas: {', '.join(DIFICULTADES)}")

    variantes = t.get("variantes", [])
    if not _es_lista_de_textos(variantes):
        E("'variantes' debe ser una lista de textos")
    else:
        for v in variantes:
            nv = normalizar(v)
            if nv == ns:
                A(f"La variante '{v}' es igual a la secreta (no aporta nada)")
            elif nv in STOPWORDS:
                A(f"La variante '{v}' es una palabra común en español; se ignorará al detectar")
    return res


def validar_mazo(tarjetas: list[dict]) -> tuple[list[ResultadoValidacion], list[str]]:
    """Valida cada tarjeta y las restricciones globales del mazo."""
    resultados = [validar_tarjeta(t) for t in tarjetas]
    errores_globales: list[str] = []
    ids, secretas = {}, []
    for t in tarjetas:
        tid = t.get("id")
        if tid in ids:
            errores_globales.append(f"Identificador repetido: {tid}")
        ids[tid] = True
        s = t.get("secreta", "")
        for anterior in secretas:
            if es_misma_palabra(s, anterior):
                errores_globales.append(f"Palabra secreta repetida: '{s}' / '{anterior}'")
        secretas.append(s)
    return resultados, errores_globales
