"""Guardado y consulta de partidas en JSON (data/games/<partida_id>.json)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from config import GAMES_DIR


def nuevo_id_partida(prefijo: str = "partida") -> str:
    return f"{prefijo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


class RegistroPartida:
    """Acumula los turnos de una partida y la guarda tras cada turno.

    Guardar tras cada turno evita perder datos si el programa se interrumpe.
    """

    def __init__(self, partida_id: str, config: dict, directorio: Path = GAMES_DIR,
                 simulado: bool = False):
        self.partida_id = partida_id
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.datos = {
            "partida_id": partida_id,
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fin": None,
            "estado": "en_curso",
            "simulado": simulado,
            "configuracion": config,
            "turnos": [],
            "marcador": None,
        }

    @property
    def ruta(self) -> Path:
        return self.directorio / f"{self.partida_id}.json"

    def agregar_turno(self, registro: dict) -> None:
        self.datos["turnos"].append(registro)
        self.guardar()

    def cerrar(self, marcador: dict, estado: str = "terminada") -> None:
        self.datos["fin"] = datetime.now().isoformat(timespec="seconds")
        self.datos["estado"] = estado
        self.datos["marcador"] = marcador
        self.guardar()

    def guardar(self) -> None:
        tmp = self.ruta.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.datos, f, ensure_ascii=False, indent=2)
        tmp.replace(self.ruta)  # escritura atómica


def listar_partidas(directorio: Path = GAMES_DIR) -> list[dict]:
    """Resumen de todas las partidas guardadas (más recientes primero)."""
    resumenes = []
    for ruta in sorted(Path(directorio).glob("*.json"), reverse=True):
        try:
            with ruta.open(encoding="utf-8") as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        m = d.get("marcador") or {}
        resumenes.append({
            "partida_id": d.get("partida_id", ruta.stem),
            "inicio": d.get("inicio"),
            "estado": d.get("estado"),
            "turnos": len(d.get("turnos", [])),
            "ganadores": m.get("ganadores", []),
            "puntos": m.get("puntos", {}),
            "simulado": d.get("simulado", False),
        })
    return resumenes


def cargar_partida(partida_id: str, directorio: Path = GAMES_DIR) -> dict:
    ruta = Path(directorio) / f"{partida_id}.json"
    if not ruta.exists():
        # permitir prefijos para no tener que teclear el id completo
        coincidencias = sorted(Path(directorio).glob(f"{partida_id}*.json"))
        if len(coincidencias) != 1:
            raise FileNotFoundError(f"No se encuentra (o es ambigua) la partida '{partida_id}'")
        ruta = coincidencias[0]
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)
