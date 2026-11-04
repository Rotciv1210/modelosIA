"""Motor de la partida: rondas, equipos, mazo, marcador y registro.

Una partida = ``rondas`` rondas; en cada ronda juega un turno cada equipo
(en orden alterno). El vigilante es común a todos los equipos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from cards.deck import Mazo, MazoAgotadoError, Tarjeta
from config import GAMES_DIR, Config
from detection.forbidden_checker import ForbiddenChecker
from detection.semantic_judge import SemanticJudge
from game.game_logger import RegistroPartida, nuevo_id_partida
from game.records import TurnRecord
from game.referee import Arbitro
from game.scoring import Marcador
from game.turn_manager import GestorTurno, TurnoAbortado
from models.ollama_client import LLMClient

Observador = Callable[[str, dict], None]


@dataclass
class ResultadoPartida:
    partida_id: str
    registros: list[TurnRecord]
    marcador: Marcador
    estado: str                    # terminada | abortada | mazo_agotado
    ruta_registro: Path | None
    avisos: list[str] = field(default_factory=list)


def crear_arbitro(cfg: Config, client: LLMClient) -> Arbitro:
    juez = None
    if cfg.juego.usar_vigilante_semantico and cfg.vigilante:
        juez = SemanticJudge(client, cfg.vigilante, umbral=cfg.juego.umbral_confianza_vigilante)
    return Arbitro(cfg.juego, ForbiddenChecker(), juez)


class MotorJuego:
    def __init__(self, cfg: Config, client: LLMClient, tarjetas: list[Tarjeta],
                 observador: Observador | None = None, directorio_partidas: Path = GAMES_DIR,
                 simulado: bool = False):
        self.cfg = cfg
        self.client = client
        self.observador = observador
        self.mazo = Mazo(tarjetas, semilla=cfg.juego.semilla_tarjetas, categorias=cfg.juego.categorias,
                         dificultades=cfg.juego.dificultades, min_prohibidas=cfg.juego.num_prohibidas)
        self.arbitro = crear_arbitro(cfg, client)
        self.turnos = GestorTurno(cfg.juego, client, self.arbitro, observador, cfg.ollama.max_tokens)
        self.directorio_partidas = directorio_partidas
        self.simulado = simulado

    def avisos_configuracion(self) -> list[str]:
        avisos = []
        if self.cfg.juego.usar_vigilante_semantico and not self.cfg.vigilante:
            avisos.append("Vigilante semántico activado pero sin modelo: solo se usará el detector automático.")
        for eq in self.cfg.equipos:
            if self.cfg.vigilante and self.cfg.vigilante == eq.descriptor and self.arbitro.juez:
                avisos.append(f"El vigilante es el mismo modelo que el descriptor de {eq.nombre}: "
                              "podría ser indulgente consigo mismo.")
        necesarias = self.cfg.juego.rondas * len(self.cfg.equipos)
        if len(self.mazo) < necesarias:
            avisos.append(f"Solo hay {len(self.mazo)} tarjetas para {necesarias} turnos: "
                          "la partida terminará antes.")
        return avisos

    def _emitir(self, evento: str, **datos) -> None:
        if self.observador:
            try:
                self.observador(evento, datos)
            except Exception:
                pass

    def jugar_partida(self) -> ResultadoPartida:
        cfg = self.cfg
        partida_id = nuevo_id_partida()
        marcador = Marcador([e.nombre for e in cfg.equipos])
        log = RegistroPartida(partida_id, cfg.to_dict(), self.directorio_partidas, self.simulado)
        avisos = self.avisos_configuracion()
        registros: list[TurnRecord] = []
        estado = "terminada"
        modelo_vig = cfg.vigilante if self.arbitro.juez else None
        self._emitir("partida_inicio", partida_id=partida_id, equipos=cfg.equipos, avisos=avisos)

        try:
            for ronda in range(1, cfg.juego.rondas + 1):
                self._emitir("ronda_inicio", ronda=ronda)
                for equipo in cfg.equipos:
                    tarjeta = self.mazo.robar()
                    rec = self.turnos.jugar(tarjeta, equipo, ronda, partida_id,
                                            cfg.juego.num_prohibidas, modelo_vig, semilla=cfg.ollama.seed)
                    marcador.registrar(rec)
                    registros.append(rec)
                    log.agregar_turno(rec.to_dict())
                    self._emitir("marcador", marcador=marcador)
        except MazoAgotadoError:
            estado = "mazo_agotado"
            avisos.append("Se acabaron las tarjetas sin repetir; la partida termina aquí.")
        except TurnoAbortado as e:
            estado = "abortada"
            marcador.registrar(e.registro)
            registros.append(e.registro)
            log.agregar_turno(e.registro.to_dict())
            avisos.append(f"Partida abortada: {e}")
        except KeyboardInterrupt:
            estado = "interrumpida"
            avisos.append("Partida interrumpida por el usuario.")

        log.cerrar(marcador.to_dict(), estado)
        self._emitir("partida_fin", marcador=marcador, estado=estado, ruta=log.ruta)
        return ResultadoPartida(partida_id, registros, marcador, estado, log.ruta, avisos)
