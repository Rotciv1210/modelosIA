"""Puntuación de turnos y marcador por equipos."""
from __future__ import annotations

from config import GameConfig
from game.records import INVALIDA, TurnRecord


def puntuar_turno(rec: TurnRecord, cfg: GameConfig) -> int:
    """+puntos_acierto si acierta, -penalizacion por cada infracción y
    -penalizacion_invalida si el turno se perdió por descripción inválida."""
    puntos = cfg.puntos_acierto if rec.acertada else 0
    puntos -= cfg.penalizacion_infraccion * rec.num_infracciones
    if rec.resultado == INVALIDA:
        puntos -= cfg.penalizacion_invalida
    return puntos


class Marcador:
    def __init__(self, equipos: list[str]):
        self.puntos = {e: 0 for e in equipos}
        self.aciertos = {e: 0 for e in equipos}
        self.infracciones = {e: 0 for e in equipos}
        self.turnos = {e: 0 for e in equipos}

    def registrar(self, rec: TurnRecord) -> None:
        e = rec.equipo
        self.puntos[e] += rec.puntuacion
        self.aciertos[e] += int(rec.acertada)
        self.infracciones[e] += rec.num_infracciones
        self.turnos[e] += 1

    def clasificacion(self) -> list[tuple[str, int]]:
        # Desempate: más aciertos, luego menos infracciones
        return sorted(self.puntos.items(),
                      key=lambda kv: (-kv[1], -self.aciertos[kv[0]], self.infracciones[kv[0]]))

    def ganadores(self) -> list[str]:
        """Equipos ganadores (varios si hay empate total)."""
        if not self.puntos:
            return []
        clas = self.clasificacion()
        mejor = clas[0][0]
        clave = (self.puntos[mejor], self.aciertos[mejor], self.infracciones[mejor])
        return [e for e, _ in clas
                if (self.puntos[e], self.aciertos[e], self.infracciones[e]) == clave]

    def to_dict(self) -> dict:
        return {"puntos": self.puntos, "aciertos": self.aciertos,
                "infracciones": self.infracciones, "turnos": self.turnos,
                "ganadores": self.ganadores()}
