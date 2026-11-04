"""Vigilante semántico: un modelo local que revisa la descripción.

Complementa al detector automático en lo que no se puede resolver con
coincidencias literales: sinónimos evidentes, traducciones no registradas,
deformaciones ortográficas, pistas de letras, perífrasis que revelan la palabra.

Garantías de diseño:
  * El vigilante recibe solo descripción + secreta + prohibidas. No conoce
    equipos, marcador ni respuestas del adivinador.
  * Su salida se valida contra un esquema fijo; el árbitro solo lee esos
    campos. Si la respuesta no es JSON válido tras un reintento, el veredicto se
    marca como no válido y NO penaliza (beneficio de la duda), pero se registra.
  * Solo cuenta como infracción si la confianza >= umbral configurado.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from detection.json_utils import extraer_json
from game.prompts import TIPOS_SEMANTICOS, mensajes_vigilante
from models.ollama_client import LLMClient, OllamaError, OllamaUnavailableError


@dataclass
class Veredicto:
    infraccion: bool
    palabra_detectada: str | None
    tipo_infraccion: str
    justificacion: str
    nivel_confianza: float
    valido: bool = True
    modelo: str | None = None
    tiempo_s: float = 0.0
    error: str | None = None
    descartado_por_arbitro: str | None = None   # motivo si el árbitro rechaza la sospecha

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origen"] = "semantica"
        return d


def _a_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "si", "sí", "yes", "1"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("false", "no", "0"):
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    return None


def parsear_veredicto(texto: str) -> Veredicto | None:
    """Convierte la salida del modelo en un Veredicto validado (o None)."""
    datos = extraer_json(texto)
    if datos is None:
        return None
    infr = _a_bool(datos.get("infraccion"))
    if infr is None:
        return None
    try:
        conf = float(datos.get("nivel_confianza", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    if conf > 1.0 and conf <= 100.0:   # algunos modelos responden en porcentaje
        conf = conf / 100.0
    conf = min(max(conf, 0.0), 1.0)
    tipo = str(datos.get("tipo_infraccion") or ("otra" if infr else "ninguna")).strip().lower()
    if tipo not in TIPOS_SEMANTICOS:
        tipo = "otra" if infr else "ninguna"
    palabra = datos.get("palabra_detectada")
    palabra = None if palabra in (None, "", "null", "None") else str(palabra)[:60]
    justif = str(datos.get("justificacion") or "")[:300]
    return Veredicto(infr, palabra, tipo, justif, conf)


class SemanticJudge:
    def __init__(self, client: LLMClient, modelo: str, umbral: float = 0.8,
                 reintentos: int = 1, max_tokens: int = 250):
        self.client = client
        self.modelo = modelo
        self.umbral = umbral
        self.reintentos = reintentos
        self.max_tokens = max_tokens

    def evaluar(self, descripcion: str, secreta: str, prohibidas: list[str],
                seed: int | None = None) -> Veredicto:
        tiempo = 0.0
        ultimo_error = None
        for intento in range(self.reintentos + 1):
            msgs = mensajes_vigilante(descripcion, secreta, prohibidas, estricto=intento > 0)
            try:
                # temperatura 0: queremos un juez lo más estable posible
                res = self.client.chat(self.modelo, msgs, json_mode=True,
                                       max_tokens=self.max_tokens, temperature=0.0, seed=seed)
            except OllamaUnavailableError:
                raise
            except OllamaError as e:
                ultimo_error = f"{type(e).__name__}: {e}"
                continue
            tiempo += res.elapsed_s
            v = parsear_veredicto(res.text)
            if v is not None:
                v.modelo, v.tiempo_s = self.modelo, tiempo
                return v
            ultimo_error = f"Respuesta no válida del vigilante: {res.text[:120]!r}"
        return Veredicto(False, None, "ninguna", "Vigilante sin veredicto válido", 0.0,
                         valido=False, modelo=self.modelo, tiempo_s=tiempo, error=ultimo_error)

    def es_infraccion(self, v: Veredicto) -> bool:
        return v.valido and v.infraccion and v.nivel_confianza >= self.umbral
