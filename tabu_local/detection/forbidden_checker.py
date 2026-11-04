"""Detección automática (determinista) de palabras prohibidas.

Para cada palabra objetivo (la secreta y cada prohibida) busca en la
descripción, por orden de gravedad:

  exacta       -> 'perro' en el texto
  morfologica  -> plural, género, diminutivo/aumentativo: 'perros', 'perrita'
  derivada     -> misma raíz de >= 4 letras: 'zapatero' para 'zapato'
  compuesta    -> el objetivo aparece dentro de otra palabra: 'paraguas' contiene 'agua'
  frase        -> objetivos de varias palabras: 'echar de menos'
  deletreo     -> letras sueltas: 'p-e-r-r-o', 'P E R R O'
  traduccion   -> variantes/traducciones conocidas: 'dog', 'gos', 'chien'

Lo que NO detecta (queda para el vigilante semántico): sinónimos ('can' por
'perro' si no está en variantes), perífrasis que revelan la palabra, rimas,
pistas de letras ('empieza por p'), traducciones no registradas, faltas de
ortografía intencionadas ('pero' por 'perro').
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from detection.text_normalizer import (STOPWORDS, base_lexica, es_infinitivo, formas_flexivas,
                                       formas_plurales, normalizar, tokenizar)

PRIORIDAD = ["exacta", "frase", "morfologica", "deletreo", "traduccion", "derivada", "compuesta"]


@dataclass(frozen=True)
class Deteccion:
    tipo: str            # uno de PRIORIDAD
    objetivo: str        # palabra secreta o prohibida afectada
    es_secreta: bool
    fragmento: str       # trozo del texto (normalizado) que la delata
    justificacion: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origen"] = "automatica"
        return d


def _buscar_frase(frase: str, texto_norm: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(frase)}(?!\w)", texto_norm) is not None


class ForbiddenChecker:
    def __init__(self, variantes_globales: dict[str, list[str]] | None = None,
                 min_len_derivada: int = 4, min_len_compuesta: int = 4):
        # variantes_globales: {"perro": ["dog", "chien"]} para cualquier objetivo
        self.variantes_globales = {normalizar(k): list(v) for k, v in (variantes_globales or {}).items()}
        self.min_len_derivada = min_len_derivada
        self.min_len_compuesta = min_len_compuesta

    # ------------------------------------------------------------------ API
    def comprobar(self, texto: str, secreta: str, prohibidas: list[str],
                  variantes_secreta: list[str] | tuple[str, ...] = ()) -> list[Deteccion]:
        """Devuelve la lista de infracciones (vacía si la descripción es limpia).

        Se devuelve como mucho UNA detección por palabra objetivo (la más grave),
        de modo que 'perro perros' cuenta como una sola infracción. Además, un mismo
        fragmento del texto solo se penaliza una vez: 'helicóptero' es la secreta y
        también deriva de la prohibida 'hélice', pero cuenta como UNA infracción.
        """
        tokens = tokenizar(texto)
        texto_norm = " ".join(tokens)
        objetivos = [(secreta, True)] + [(p, False) for p in prohibidas]
        detecciones: list[Deteccion] = []
        usados: set[str] = set()
        for objetivo, es_secreta in objetivos:
            candidatas = []
            d = self._literal(objetivo, es_secreta, tokens, texto_norm)
            if d:
                candidatas.append(d)
            d = self._deletreo(objetivo, es_secreta, tokens)
            if d:
                candidatas.append(d)
            variantes = list(self.variantes_globales.get(normalizar(objetivo), []))
            if es_secreta:
                variantes += list(variantes_secreta)
            d = self._traduccion(objetivo, es_secreta, variantes, tokens, texto_norm)
            if d:
                candidatas.append(d)
            candidatas = [c for c in candidatas if c.fragmento not in usados]
            if candidatas:
                candidatas.sort(key=lambda x: PRIORIDAD.index(x.tipo))
                detecciones.append(candidatas[0])
                usados.add(candidatas[0].fragmento)
        return detecciones

    # ------------------------------------------------------------- internas
    def _literal(self, objetivo: str, es_secreta: bool, tokens: list[str],
                 texto_norm: str) -> Deteccion | None:
        obj = normalizar(objetivo)
        if not obj:
            return None
        etiqueta = "la palabra secreta" if es_secreta else "la palabra prohibida"

        # Objetivos de varias palabras ("echar de menos", "bola de nieve")
        if " " in obj:
            if _buscar_frase(obj, texto_norm):
                return Deteccion("frase", objetivo, es_secreta, obj, f"Aparece {etiqueta} '{objetivo}'")
            pal = obj.split()
            for forma in formas_plurales(pal[-1]):
                frase = " ".join(pal[:-1] + [forma])
                if _buscar_frase(frase, texto_norm):
                    return Deteccion("morfologica", objetivo, es_secreta, frase,
                                     f"Aparece una forma flexionada de {etiqueta} '{objetivo}'")
            # escrita junta: 'arcoiris' para 'arco iris'
            junta = obj.replace(" ", "")
            if junta in tokens:
                return Deteccion("frase", objetivo, es_secreta, junta, f"Aparece {etiqueta} escrita junta")
            return None

        if obj in tokens:
            return Deteccion("exacta", objetivo, es_secreta, obj, f"Aparece literalmente {etiqueta} '{objetivo}'")

        formas = formas_flexivas(obj)
        for tok in tokens:
            if tok in formas:
                return Deteccion("morfologica", objetivo, es_secreta, tok,
                                 f"'{tok}' es plural/género/diminutivo de {etiqueta} '{objetivo}'")

        base = base_lexica(obj)
        # Verbos: cualquier forma que empiece por la raíz ('ladra', 'ladrando').
        # Nombres: exigimos 2 letras más para no confundir 'libro' con 'libre'.
        extra = 1 if es_infinitivo(obj) else 2
        if len(base) >= self.min_len_derivada:
            for tok in tokens:
                if tok not in STOPWORDS and tok.startswith(base) and len(tok) >= len(base) + extra:
                    return Deteccion("derivada", objetivo, es_secreta, tok,
                                     f"'{tok}' comparte la raíz '{base}' con {etiqueta} '{objetivo}'")

        if len(obj) >= self.min_len_compuesta:
            for tok in tokens:
                if tok != obj and obj in tok[1:]:
                    return Deteccion("compuesta", objetivo, es_secreta, tok,
                                     f"'{tok}' contiene {etiqueta} '{objetivo}' (palabra compuesta)")
        return None

    def _deletreo(self, objetivo: str, es_secreta: bool, tokens: list[str]) -> Deteccion | None:
        """Detecta secuencias de letras sueltas que forman el objetivo: 'p e r r o'."""
        obj = normalizar(objetivo).replace(" ", "")
        if len(obj) < 3:
            return None
        formas = formas_plurales(obj)
        racha: list[str] = []
        for tok in tokens + [""]:              # centinela para cerrar la última racha
            if len(tok) == 1:
                racha.append(tok)
                continue
            if len(racha) >= 3:
                unida = "".join(racha)
                if unida in formas or obj in unida:
                    return Deteccion("deletreo", objetivo, es_secreta, " ".join(racha),
                                     f"Se deletrea '{objetivo}' con letras sueltas")
            racha = []
        return None

    def _traduccion(self, objetivo: str, es_secreta: bool, variantes: list[str],
                    tokens: list[str], texto_norm: str) -> Deteccion | None:
        obj = normalizar(objetivo)
        for v in variantes:
            vn = normalizar(v)
            if not vn or vn == obj or vn in STOPWORDS:
                continue
            if " " in vn:
                encontrado = _buscar_frase(vn, texto_norm)
            else:
                formas = formas_plurales(vn)
                encontrado = any(t in formas for t in tokens)
            if encontrado:
                return Deteccion("traduccion", objetivo, es_secreta, vn,
                                 f"'{vn}' es una traducción/variante de '{objetivo}'")
        return None
