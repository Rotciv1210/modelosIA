"""Modelo de tarjeta, carga desde JSON y mazo sin repetición."""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cards.card_validator import validar_mazo


class MazoAgotadoError(Exception):
    """No quedan tarjetas sin usar en la sesión."""


class TarjetasInvalidasError(ValueError):
    pass


@dataclass(frozen=True)
class Tarjeta:
    id: str
    secreta: str
    prohibidas: tuple[str, ...]          # 3-5 principales (juego normal)
    categoria: str
    dificultad: str
    prohibidas_extra: tuple[str, ...] = ()  # solo para condiciones experimentales > 5
    variantes: tuple[str, ...] = field(default=())  # traducciones/variantes de la secreta

    @property
    def max_prohibidas(self) -> int:
        return len(self.prohibidas) + len(self.prohibidas_extra)

    def prohibidas_para(self, n: int) -> list[str]:
        """Las n primeras prohibidas (principales y luego extra, por relevancia).

        Las condiciones son anidadas: las 3 de la condición A están incluidas en
        las 5 de B y estas en las 7 de C. Así solo cambia el número de palabras.
        """
        todas = list(self.prohibidas) + list(self.prohibidas_extra)
        if n > len(todas):
            raise ValueError(f"La tarjeta {self.id} solo tiene {len(todas)} prohibidas (se piden {n})")
        return todas[:n]

    @classmethod
    def desde_dict(cls, d: dict) -> "Tarjeta":
        return cls(id=str(d["id"]), secreta=d["secreta"], prohibidas=tuple(d["prohibidas"]),
                   categoria=d["categoria"], dificultad=d["dificultad"],
                   prohibidas_extra=tuple(d.get("prohibidas_extra", [])),
                   variantes=tuple(d.get("variantes", [])))

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("prohibidas", "prohibidas_extra", "variantes"):
            d[k] = list(d[k])
        return d


def leer_json_tarjetas(ruta: str | Path) -> list[dict]:
    with Path(ruta).open(encoding="utf-8") as f:
        datos = json.load(f)
    return datos["tarjetas"] if isinstance(datos, dict) else datos


def cargar_tarjetas(rutas: list[str | Path] | str | Path, estricto: bool = True) -> list[Tarjeta]:
    """Carga y valida tarjetas de uno o varios ficheros.

    estricto=True  -> cualquier error aborta (útil en pruebas y experimentos).
    estricto=False -> las tarjetas inválidas se descartan con un aviso.
    """
    if isinstance(rutas, (str, Path)):
        rutas = [rutas]
    crudas: list[dict] = []
    for r in rutas:
        if Path(r).exists():
            crudas += leer_json_tarjetas(r)
    resultados, globales = validar_mazo(crudas)
    malas = {r.id for r in resultados if not r.valida}
    if estricto and (malas or globales):
        detalle = [f"{r.id}: {'; '.join(r.errores)}" for r in resultados if not r.valida] + globales
        raise TarjetasInvalidasError("Tarjetas inválidas:\n  " + "\n  ".join(detalle))
    tarjetas, vistas = [], set()
    for d, r in zip(crudas, resultados):
        if r.valida and d["id"] not in vistas:
            tarjetas.append(Tarjeta.desde_dict(d))
            vistas.add(d["id"])
    return tarjetas


class Mazo:
    """Reparte tarjetas aleatorias sin repetir ninguna durante la sesión."""

    def __init__(self, tarjetas: list[Tarjeta], semilla: int | None = None,
                 categorias: list[str] | None = None, dificultades: list[str] | None = None,
                 min_prohibidas: int = 0):
        filtradas = [t for t in tarjetas
                     if (not categorias or t.categoria in categorias)
                     and (not dificultades or t.dificultad in dificultades)
                     and t.max_prohibidas >= min_prohibidas]
        self._rng = random.Random(semilla)
        self._pendientes = list(filtradas)
        self._rng.shuffle(self._pendientes)
        self.usadas: list[str] = []

    def __len__(self) -> int:
        return len(self._pendientes)

    def robar(self) -> Tarjeta:
        if not self._pendientes:
            raise MazoAgotadoError("No quedan tarjetas sin usar en esta sesión")
        t = self._pendientes.pop()
        assert t.id not in self.usadas  # garantía: nunca se repite una tarjeta
        self.usadas.append(t.id)
        return t
