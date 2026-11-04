"""Registro estructurado de cada turno (= una ronda de un equipo con una tarjeta)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# Resultados posibles de un turno
ACIERTO = "acierto"          # el adivinador acertó
FALLO = "fallo"              # se agotaron los intentos sin acertar
INFRACCION = "infraccion"    # el descriptor rompió las reglas y se cortó el turno
INVALIDA = "invalida"        # el descriptor no produjo una descripción válida
ERROR = "error"              # error técnico (timeout, conexión...) que impidió seguir


@dataclass
class TurnRecord:
    partida_id: str
    ronda: int
    equipo: str
    modelo_descriptor: str
    modelo_adivinador: str
    modelo_vigilante: str | None
    tarjeta_id: str
    palabra_secreta: str
    palabras_prohibidas: list[str]
    categoria: str
    dificultad: str
    num_prohibidas: int
    max_intentos: int
    semilla: int | None = None
    descripciones: list[str] = field(default_factory=list)          # pistas entregadas al adivinador
    descripciones_rechazadas: list[dict] = field(default_factory=list)  # inválidas o con infracción
    respuestas_adivinador: list[str] = field(default_factory=list)
    resultado: str = FALLO
    acertada: bool = False
    intentos_usados: int = 0
    infracciones: list[dict] = field(default_factory=list)
    veredictos_vigilante: list[dict] = field(default_factory=list)
    descripciones_invalidas: int = 0
    respuestas_invalidas: int = 0
    respuestas_repetidas: int = 0
    puntuacion: int = 0
    tiempos_descriptor_s: list[float] = field(default_factory=list)
    tiempos_adivinador_s: list[float] = field(default_factory=list)
    tiempos_vigilante_s: list[float] = field(default_factory=list)
    tiempo_total_s: float = 0.0
    errores: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # --------------------------------------------------------------- derivados
    @property
    def num_infracciones(self) -> int:
        return len(self.infracciones)

    def infracciones_por_origen(self, origen: str) -> int:
        return sum(1 for i in self.infracciones if i.get("origen") == origen)

    @staticmethod
    def _media(v: list[float]) -> float | None:
        return round(sum(v) / len(v), 4) if v else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["num_infracciones"] = self.num_infracciones
        d["tiempo_medio_descriptor_s"] = self._media(self.tiempos_descriptor_s)
        d["tiempo_medio_adivinador_s"] = self._media(self.tiempos_adivinador_s)
        d["tiempo_medio_vigilante_s"] = self._media(self.tiempos_vigilante_s)
        return d

    @classmethod
    def desde_dict(cls, d: dict) -> "TurnRecord":
        campos = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**campos)
