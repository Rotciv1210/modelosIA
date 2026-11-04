"""Desarrollo de un turno: un equipo intenta adivinar una tarjeta.

Secuencia por intento:
  1. El descriptor genera una pista (con reintentos si es vacía/inválida).
  2. El árbitro la revisa (detector automático + vigilante semántico).
     - Si hay infracción: penalización y, por defecto, fin del turno. La pista
       NUNCA llega al adivinador.
  3. El adivinador recibe todas las pistas válidas y sus fallos previos y responde.
  4. Si acierta, fin; si no, el descriptor da una pista adicional.

Los errores técnicos (timeout, respuesta rota) se registran y el turno sigue o
termina de forma controlada. Solo se propagan los errores que impiden seguir
jugando (Ollama caído o modelo no instalado).
"""
from __future__ import annotations

import time
from typing import Callable

from cards.deck import Tarjeta
from config import GameConfig, TeamConfig
from detection.text_normalizer import es_misma_palabra
from game.records import ACIERTO, ERROR, FALLO, INFRACCION, INVALIDA, TurnRecord
from game.referee import Arbitro
from game.roles import Adivinador, Descriptor
from game.scoring import puntuar_turno
from models.ollama_client import (LLMClient, ModelNotFoundError, OllamaError,
                                  OllamaUnavailableError)

Observador = Callable[[str, dict], None]
ERRORES_FATALES = (OllamaUnavailableError, ModelNotFoundError)


def _semilla(base: int | None, intento: int, reintento: int) -> int | None:
    """Semilla derivada y determinista para cada llamada del turno."""
    return None if base is None else base + 101 * intento + reintento


class GestorTurno:
    def __init__(self, cfg: GameConfig, client: LLMClient, arbitro: Arbitro,
                 observador: Observador | None = None, max_tokens_descriptor: int = 200):
        self.cfg = cfg
        self.client = client
        self.arbitro = arbitro
        self.observador = observador
        self.max_tokens_descriptor = max_tokens_descriptor

    def _emitir(self, evento: str, **datos) -> None:
        if self.observador:
            try:
                self.observador(evento, datos)
            except Exception:  # la interfaz nunca debe tumbar la partida
                pass

    # ------------------------------------------------------------------ turno
    def jugar(self, tarjeta: Tarjeta, equipo: TeamConfig, ronda: int, partida_id: str,
              num_prohibidas: int, modelo_vigilante: str | None,
              semilla: int | None = None) -> TurnRecord:
        cfg = self.cfg
        prohibidas = tarjeta.prohibidas_para(num_prohibidas)
        rec = TurnRecord(
            partida_id=partida_id, ronda=ronda, equipo=equipo.nombre,
            modelo_descriptor=equipo.descriptor, modelo_adivinador=equipo.adivinador,
            modelo_vigilante=modelo_vigilante, tarjeta_id=tarjeta.id,
            palabra_secreta=tarjeta.secreta, palabras_prohibidas=prohibidas,
            categoria=tarjeta.categoria, dificultad=tarjeta.dificultad,
            num_prohibidas=num_prohibidas, max_intentos=cfg.intentos_por_tarjeta, semilla=semilla)
        descriptor = Descriptor(self.client, equipo.descriptor, self.max_tokens_descriptor)
        adivinador = Adivinador(self.client, equipo.adivinador)
        self._emitir("turno_inicio", equipo=equipo.nombre, ronda=ronda, tarjeta=tarjeta, prohibidas=prohibidas)

        inicio = time.perf_counter()
        fallidas: list[str] = []
        fin: str | None = None
        try:
            for intento in range(1, cfg.intentos_por_tarjeta + 1):
                rec.intentos_usados = intento
                # 1) descriptor
                pista, solo_errores = self._obtener_pista(descriptor, tarjeta, prohibidas, fallidas,
                                                          rec, intento, semilla)
                if pista is None:
                    fin = ERROR if solo_errores else INVALIDA
                    break
                self._emitir("descripcion_generada", texto=pista, intento=intento)
                # 2) árbitro + vigilante
                infracciones, veredicto = self.arbitro.revisar_descripcion(
                    pista, tarjeta.secreta, prohibidas, tarjeta.variantes, seed=semilla)
                if veredicto is not None:
                    v = veredicto.to_dict() | {"intento": intento, "descripcion": pista}
                    rec.veredictos_vigilante.append(v)
                    rec.tiempos_vigilante_s.append(veredicto.tiempo_s)
                    if veredicto.error:
                        rec.errores.append(f"vigilante (intento {intento}): {veredicto.error}")
                    self._emitir("veredicto", veredicto=v)
                if infracciones:
                    for i in infracciones:
                        i["intento"] = intento
                    rec.infracciones.extend(infracciones)
                    rec.descripciones_rechazadas.append({"intento": intento, "texto": pista, "motivo": "infraccion"})
                    self._emitir("infraccion", descripcion=pista, infracciones=infracciones)
                    if cfg.fin_turno_por_infraccion:
                        fin = INFRACCION
                        break
                    continue
                rec.descripciones.append(pista)
                self._emitir("descripcion", texto=pista, intento=intento)
                # 3) adivinador
                resp = self._obtener_respuesta(adivinador, rec, fallidas, intento, semilla)
                rec.respuestas_adivinador.append(resp)
                acierto = self.arbitro.es_acierto(resp, tarjeta.secreta)
                self._emitir("respuesta", respuesta=resp, acierto=acierto, intento=intento)
                if acierto:
                    rec.acertada = True
                    fin = ACIERTO
                    break
                if resp:
                    fallidas.append(resp)
        except ERRORES_FATALES as e:
            rec.errores.append(f"{type(e).__name__}: {e}")
            rec.resultado = ERROR
            rec.tiempo_total_s = round(time.perf_counter() - inicio, 3)
            rec.puntuacion = puntuar_turno(rec, cfg)
            self._emitir("error", mensaje=str(e))
            raise TurnoAbortado(rec) from e

        rec.resultado = fin or FALLO
        rec.tiempo_total_s = round(time.perf_counter() - inicio, 3)
        rec.puntuacion = puntuar_turno(rec, cfg)
        self._emitir("turno_fin", registro=rec)
        return rec

    # -------------------------------------------------------------- auxiliares
    def _obtener_pista(self, descriptor: Descriptor, tarjeta: Tarjeta, prohibidas: list[str],
                       fallidas: list[str], rec: TurnRecord, intento: int,
                       semilla: int | None) -> tuple[str | None, bool]:
        """Devuelve (pista_valida | None, todos_los_fallos_fueron_tecnicos)."""
        solo_errores = True
        for k in range(self.cfg.reintentos_respuesta_invalida + 1):
            try:
                res = descriptor.describir(tarjeta.secreta, prohibidas, rec.descripciones, fallidas,
                                           self.cfg.max_palabras_descripcion, estricto=k > 0,
                                           seed=_semilla(semilla, intento, k))
            except ERRORES_FATALES:
                raise
            except OllamaError as e:
                rec.errores.append(f"descriptor (intento {intento}.{k}): {type(e).__name__}: {e}")
                self._emitir("error", mensaje=f"Descriptor: {e}")
                continue
            solo_errores = False
            rec.tiempos_descriptor_s.append(round(res.elapsed_s, 4))
            val = self.arbitro.limpiar_descripcion(res.text, rec.descripciones)
            if val.valido:
                if val.truncada:
                    rec.errores.append(f"aviso: descripción truncada a {self.cfg.max_palabras_descripcion} palabras")
                return val.texto, False
            rec.descripciones_invalidas += 1
            rec.descripciones_rechazadas.append({"intento": intento, "texto": (res.text or "")[:300],
                                                 "motivo": val.motivo})
            self._emitir("descripcion_invalida", motivo=val.motivo, texto=res.text)
        return None, solo_errores

    def _obtener_respuesta(self, adivinador: Adivinador, rec: TurnRecord, fallidas: list[str],
                           intento: int, semilla: int | None) -> str | None:
        insistir = False
        repetida = None
        for k in range(self.cfg.reintentos_respuesta_invalida + 1):
            try:
                res = adivinador.adivinar(rec.descripciones, fallidas, intento, self.cfg.intentos_por_tarjeta,
                                          insistir_distinta=insistir, seed=_semilla(semilla, intento, k))
            except ERRORES_FATALES:
                raise
            except OllamaError as e:
                rec.errores.append(f"adivinador (intento {intento}.{k}): {type(e).__name__}: {e}")
                self._emitir("error", mensaje=f"Adivinador: {e}")
                continue
            rec.tiempos_adivinador_s.append(round(res.elapsed_s, 4))
            resp = self.arbitro.extraer_respuesta(res.text)
            if resp is None:
                rec.respuestas_invalidas += 1
                insistir = True
                continue
            if any(es_misma_palabra(resp, f) for f in fallidas):
                rec.respuestas_repetidas += 1
                repetida = resp
                insistir = True
                continue
            return resp
        return repetida  # si solo repite, cuenta como intento fallido con esa respuesta


class TurnoAbortado(Exception):
    """Error que impide continuar (Ollama caído / modelo ausente). Lleva el registro parcial."""

    def __init__(self, registro: TurnRecord):
        super().__init__(registro.errores[-1] if registro.errores else "Turno abortado")
        self.registro = registro
