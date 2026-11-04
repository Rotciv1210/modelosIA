"""Árbitro: limpia y valida respuestas, detecta infracciones y decide aciertos.

El árbitro es código Python determinista. Los modelos nunca deciden el
resultado directamente: el vigilante solo emite un veredicto estructurado que
el árbitro acepta o descarta según el umbral de confianza y el modo
configurado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from config import GameConfig
from detection.forbidden_checker import ForbiddenChecker
from detection.json_utils import extraer_json
from detection.semantic_judge import SemanticJudge, Veredicto
from detection.text_normalizer import ARTICULOS, es_misma_palabra, normalizar

MAX_CARACTERES = 800  # corte de seguridad para respuestas desmesuradas

# Frases que indican que el modelo habla del juego/su rol en vez de describir
_META = re.compile(
    r"palabras? secretas?|palabras? prohibidas?|reglas del juego|\bcomo descriptor\b|"
    r"\bsoy (el|un) (descriptor|adivinador)\b|\bno puedo (decir|usar|mencionar)\b|"
    r"\blo siento\b|\bcomo (modelo|asistente|ia)\b",
    re.IGNORECASE)
_ETIQUETA = re.compile(r"^\s*(\*\*)?\s*(descripci[oó]n|pista( nueva| adicional)?|respuesta)\s*\d*\s*(\*\*)?\s*[:\-–]\s*",
                       re.IGNORECASE)
_COMILLAS = "\"'«»“”‘’*`"


def recortar_por_frases(texto: str, max_palabras: int) -> str:
    """Recorta un texto largo sin dejar frases a medias.

    Se queda con las frases completas que caben en ``max_palabras``. Si ni
    siquiera cabe la primera frase, corta por palabras y añade '…'.
    """
    frases = re.findall(r"[^.!?…]+[.!?…]+[\"'»”)]*|[^.!?…]+$", texto)
    resultado: list[str] = []
    usadas = 0
    for f in (f.strip() for f in frases):
        n = len(f.split())
        if usadas + n > max_palabras:
            break
        resultado.append(f)
        usadas += n
    if resultado:
        return " ".join(resultado)
    return " ".join(texto.split()[:max_palabras]).rstrip(",;:") + "…"


def cita_en_texto(cita: str | None, texto: str) -> bool:
    """¿Aparece la cita (normalizada) dentro del texto (normalizado)?"""
    nc = normalizar(cita)
    return bool(nc) and f" {nc} " in f" {normalizar(texto)} "


@dataclass
class TextoValidado:
    texto: str | None
    motivo: str | None = None     # por qué es inválido (si lo es)
    truncada: bool = False

    @property
    def valido(self) -> bool:
        return self.texto is not None


class Arbitro:
    def __init__(self, cfg: GameConfig, checker: ForbiddenChecker | None = None,
                 juez: SemanticJudge | None = None):
        self.cfg = cfg
        self.checker = checker or ForbiddenChecker()
        self.juez = juez

    # ------------------------------------------------------- descripciones
    def limpiar_descripcion(self, bruto: str | None, pistas_previas: list[str]) -> TextoValidado:
        texto = (bruto or "")[:MAX_CARACTERES * 2].strip()
        texto = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), texto, flags=re.DOTALL)
        datos = extraer_json(texto) if texto.startswith("{") else None
        if datos:  # algún modelo responde {"descripcion": "..."}
            texto = str(next((v for k, v in datos.items() if isinstance(v, str)), ""))
        texto = _ETIQUETA.sub("", texto)
        texto = " ".join(l.strip() for l in texto.splitlines() if l.strip())
        texto = texto.strip(_COMILLAS + " ").strip()
        texto = re.sub(r"\s+", " ", texto)[:MAX_CARACTERES]

        if not texto:
            return TextoValidado(None, "vacia")
        palabras = texto.split()
        if len(palabras) < 2:
            return TextoValidado(None, "demasiado_corta")
        if _META.search(texto):
            return TextoValidado(None, "habla_del_juego_o_del_rol")
        if any(normalizar(texto) == normalizar(p) for p in pistas_previas):
            return TextoValidado(None, "repetida")
        truncada = False
        if len(palabras) > self.cfg.max_palabras_descripcion:
            texto = recortar_por_frases(texto, self.cfg.max_palabras_descripcion)
            truncada = True
        return TextoValidado(texto, None, truncada)

    def revisar_descripcion(self, descripcion: str, secreta: str, prohibidas: list[str],
                            variantes: tuple[str, ...] | list[str] = (),
                            seed: int | None = None) -> tuple[list[dict], Veredicto | None]:
        """Devuelve (infracciones, veredicto_del_vigilante).

        1º detector automático; si no encuentra nada y hay vigilante, 2º revisión
        semántica. El vigilante solo se consulta cuando hace falta (ahorra tiempo
        y evita que su ruido se sume a infracciones ya demostradas).
        """
        infracciones = [d.to_dict() for d in self.checker.comprobar(descripcion, secreta, prohibidas, variantes)]
        veredicto = None
        if not infracciones and self.juez is not None:
            veredicto = self.juez.evaluar(descripcion, secreta, prohibidas, seed=seed)
            # El vigilante debe aportar PRUEBAS: el fragmento que cita tiene que
            # estar literalmente en la descripción. Si no (p. ej. dice que aparece
            # la palabra secreta y no es verdad), el árbitro descarta la sospecha.
            if self.juez.es_infraccion(veredicto) and not cita_en_texto(veredicto.palabra_detectada, descripcion):
                veredicto.descartado_por_arbitro = (
                    f"El fragmento citado ('{veredicto.palabra_detectada or '—'}') no aparece en la descripción")
            if (self.juez.es_infraccion(veredicto) and not veredicto.descartado_por_arbitro
                    and self.cfg.vigilante_modo == "penaliza"):
                infracciones.append({
                    "origen": "semantica",
                    "tipo": veredicto.tipo_infraccion,
                    "objetivo": veredicto.palabra_detectada,
                    "es_secreta": None,
                    "fragmento": veredicto.palabra_detectada,
                    "justificacion": veredicto.justificacion,
                    "confianza": veredicto.nivel_confianza,
                })
        return infracciones, veredicto

    # ----------------------------------------------------------- respuestas
    @staticmethod
    def extraer_respuesta(bruto: str | None) -> str | None:
        """Saca la palabra propuesta por el adivinador (JSON o texto libre)."""
        if not bruto or not bruto.strip():
            return None
        datos = extraer_json(bruto)
        if datos:
            for clave in ("respuesta", "palabra", "answer", "respuesta_final"):
                if isinstance(datos.get(clave), str):
                    candidato = datos[clave]
                    break
            else:
                return None
        else:
            lineas = [l for l in bruto.strip().splitlines() if l.strip()]
            candidato = lineas[0] if lineas else ""
            candidato = _ETIQUETA.sub("", candidato)
            if ":" in candidato:                 # "Creo que es: el perro" -> "el perro"
                candidato = candidato.rsplit(":", 1)[1]
        candidato = candidato.strip(_COMILLAS + " .,;:!¡?¿").strip()
        palabras = candidato.split()
        while len(palabras) > 1 and normalizar(palabras[0]) in ARTICULOS:
            palabras = palabras[1:]          # "el perro" -> "perro" (conservando tildes)
        candidato = " ".join(palabras)
        if not candidato or len(candidato.split()) > 4 or len(candidato) > 40:
            return None
        return candidato.lower()

    @staticmethod
    def es_acierto(respuesta: str | None, secreta: str) -> bool:
        return bool(respuesta) and es_misma_palabra(respuesta, secreta)
