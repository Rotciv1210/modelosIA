"""Configuración del proyecto.

Toda la configuración vive en ``config.json`` (o en el fichero que se pase con
``--config``). Así se pueden cambiar modelos, rondas, penalizaciones, etc. sin
tocar el código. Este módulo carga el JSON, rellena valores por defecto y
valida que los valores tengan sentido.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
CARDS_DIR = BASE_DIR / "cards"
GAMES_DIR = BASE_DIR / "data" / "games"
RESULTS_DIR = BASE_DIR / "data" / "results"

MAX_PROHIBIDAS = 7  # máximo que admite el mazo (5 principales + 2 extra)


class ConfigError(ValueError):
    """Error de configuración (valores inválidos o claves desconocidas)."""


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    timeout_s: float = 90.0          # tiempo máximo de respuesta de un modelo
    connect_timeout_s: float = 5.0   # tiempo máximo para conectar con Ollama
    temperature: float = 0.7
    seed: int | None = 42            # semilla de muestreo (reproducibilidad)
    max_tokens: int = 200            # límite de tokens generados por respuesta
    keep_alive: str = "15m"          # cuánto tiempo mantiene Ollama el modelo en memoria
    num_gpu: int | None = 0          # capas en GPU: 0 = solo CPU (los modelos caben a la vez en RAM); null = automático
    permitir_host_no_local: bool = False  # seguridad: solo inferencia local


@dataclass
class GameConfig:
    rondas: int = 3
    intentos_por_tarjeta: int = 3
    num_prohibidas: int = 5
    puntos_acierto: int = 1
    penalizacion_infraccion: int = 1
    penalizacion_invalida: int = 0
    fin_turno_por_infraccion: bool = True
    max_palabras_descripcion: int = 40
    reintentos_respuesta_invalida: int = 2
    usar_vigilante_semantico: bool = True
    vigilante_modo: str = "penaliza"     # "penaliza" | "consultivo"
    umbral_confianza_vigilante: float = 0.8
    semilla_tarjetas: int | None = None
    ficheros_tarjetas: list[str] = field(default_factory=lambda: ["cards/cards.json"])
    categorias: list[str] | None = None
    dificultades: list[str] | None = None


@dataclass
class TeamConfig:
    nombre: str
    descriptor: str
    adivinador: str


@dataclass
class ExperimentConfig:
    condiciones: list[int] = field(default_factory=lambda: [3, 5, 7])
    repeticiones: int = 2
    num_tarjetas: int = 30
    semilla: int = 1234
    dificultades: list[str] | None = None


@dataclass
class Config:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    juego: GameConfig = field(default_factory=GameConfig)
    equipos: list[TeamConfig] = field(default_factory=list)
    vigilante: str | None = None
    experimento: ExperimentConfig = field(default_factory=ExperimentConfig)

    # ------------------------------------------------------------------ util
    def modelos_necesarios(self, incluir_vigilante: bool | None = None) -> list[str]:
        """Lista (sin repetir) de modelos que hacen falta para jugar."""
        if incluir_vigilante is None:
            incluir_vigilante = self.juego.usar_vigilante_semantico
        modelos: list[str] = []
        for eq in self.equipos:
            for m in (eq.descriptor, eq.adivinador):
                if m not in modelos:
                    modelos.append(m)
        if incluir_vigilante and self.vigilante and self.vigilante not in modelos:
            modelos.append(self.vigilante)
        return modelos

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ruta_tarjetas(self) -> list[Path]:
        rutas = []
        for r in self.juego.ficheros_tarjetas:
            p = Path(r)
            rutas.append(p if p.is_absolute() else BASE_DIR / p)
        return rutas


# ---------------------------------------------------------------------- carga
def _construir(cls, datos: dict[str, Any] | None, seccion: str):
    """Crea un dataclass a partir de un diccionario, rechazando claves desconocidas."""
    datos = dict(datos or {})
    validas = {f.name for f in fields(cls)}
    desconocidas = set(datos) - validas
    if desconocidas:
        raise ConfigError(f"Claves desconocidas en '{seccion}': {sorted(desconocidas)}")
    return cls(**datos)


def config_desde_dict(datos: dict[str, Any]) -> Config:
    claves = {"ollama", "juego", "equipos", "vigilante", "experimento"}
    desconocidas = set(datos) - claves
    if desconocidas:
        raise ConfigError(f"Secciones desconocidas en la configuración: {sorted(desconocidas)}")
    equipos = []
    for i, eq in enumerate(datos.get("equipos", [])):
        equipos.append(_construir(TeamConfig, eq, f"equipos[{i}]"))
    cfg = Config(
        ollama=_construir(OllamaConfig, datos.get("ollama"), "ollama"),
        juego=_construir(GameConfig, datos.get("juego"), "juego"),
        equipos=equipos,
        vigilante=datos.get("vigilante"),
        experimento=_construir(ExperimentConfig, datos.get("experimento"), "experimento"),
    )
    validar_config(cfg)
    return cfg


def cargar_config(ruta: str | Path | None = None) -> Config:
    ruta = Path(ruta) if ruta else DEFAULT_CONFIG_PATH
    if not ruta.exists():
        raise ConfigError(f"No existe el fichero de configuración: {ruta}")
    with ruta.open(encoding="utf-8") as f:
        try:
            datos = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"El fichero {ruta} no es JSON válido: {e}") from e
    return config_desde_dict(datos)


def validar_config(cfg: Config) -> None:
    j = cfg.juego
    errores = []
    if j.rondas < 1:
        errores.append("juego.rondas debe ser >= 1")
    if j.intentos_por_tarjeta < 1:
        errores.append("juego.intentos_por_tarjeta debe ser >= 1")
    if not 1 <= j.num_prohibidas <= MAX_PROHIBIDAS:
        errores.append(f"juego.num_prohibidas debe estar entre 1 y {MAX_PROHIBIDAS}")
    if j.max_palabras_descripcion < 5:
        errores.append("juego.max_palabras_descripcion debe ser >= 5")
    if j.reintentos_respuesta_invalida < 0:
        errores.append("juego.reintentos_respuesta_invalida debe ser >= 0")
    if j.vigilante_modo not in ("penaliza", "consultivo"):
        errores.append("juego.vigilante_modo debe ser 'penaliza' o 'consultivo'")
    if not 0.0 <= j.umbral_confianza_vigilante <= 1.0:
        errores.append("juego.umbral_confianza_vigilante debe estar entre 0 y 1")
    if cfg.ollama.timeout_s <= 0:
        errores.append("ollama.timeout_s debe ser > 0")
    if not cfg.equipos:
        errores.append("Debe haber al menos un equipo en 'equipos'")
    nombres = [e.nombre for e in cfg.equipos]
    if len(set(nombres)) != len(nombres):
        errores.append("Los nombres de los equipos deben ser distintos")
    for c in cfg.experimento.condiciones:
        if not 1 <= c <= MAX_PROHIBIDAS:
            errores.append(f"experimento.condiciones: {c} fuera de rango (1-{MAX_PROHIBIDAS})")
    if cfg.experimento.repeticiones < 1:
        errores.append("experimento.repeticiones debe ser >= 1")
    if errores:
        raise ConfigError("Configuración inválida:\n  - " + "\n  - ".join(errores))


def guardar_config(cfg: Config, ruta: str | Path) -> None:
    with Path(ruta).open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
