"""Interfaz gráfica: servidor web local (solo biblioteca estándar).

Arranca un pequeño servidor en http://127.0.0.1:8765 y abre el navegador. La
página (gui/static/index.html) habla con esta API:

  GET  /api/estado          Ollama, modelos instalados y configuración por defecto
  POST /api/partida         empieza una partida (en un hilo aparte)
  GET  /api/eventos?desde=N eventos de la partida en curso a partir del N
  POST /api/continuar       avanza al siguiente turno (modo con pausas)
  POST /api/detener         detiene la partida
  GET  /api/historial       partidas guardadas
  GET  /api/partida?id=X    detalle de una partida guardada

El servidor solo escucha en 127.0.0.1: no es accesible desde otros equipos.
Reutiliza exactamente el mismo motor que la versión de consola.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cards.deck import cargar_tarjetas
from config import (GAMES_DIR, MAX_PROHIBIDAS, ConfigError, TeamConfig, cargar_config,
                    validar_config)
from game.game_engine import MotorJuego
from game.game_logger import cargar_partida, listar_partidas
from models.fake_client import SimulatedClient
from models.model_manager import ModelManager, precargar
from models.ollama_client import OllamaClient, es_modelo_remoto

STATIC = Path(__file__).resolve().parent / "static"


class DetenerPartida(KeyboardInterrupt):
    """Se lanza desde el observador para cortar la partida (el motor la trata
    como una interrupción y guarda el registro con estado 'interrumpida')."""


# ---------------------------------------------------------------- sesión
class SesionJuego:
    """Estado de la partida en curso, compartido entre el hilo del juego y la web."""

    def __init__(self):
        self.lock = threading.Lock()
        self.eventos: list[dict] = []
        self.activa = False
        self.pausar = False
        self.detener = False
        self.continuar = threading.Event()
        self.hilo: threading.Thread | None = None
        self.vigilante: str | None = None
        self.rondas = 0
        self.intentos = 0
        self.turnos_totales = 0
        self.turnos_jugados = 0

    def emitir(self, tipo: str, **datos) -> None:
        with self.lock:
            self.eventos.append({"n": len(self.eventos), "tipo": tipo, **datos})

    def desde(self, n: int) -> list[dict]:
        with self.lock:
            return self.eventos[n:]

    # --- observador del motor: traduce objetos Python a JSON -----------------
    def observador(self, evento: str, d: dict) -> None:
        if self.detener and evento != "partida_fin":
            raise DetenerPartida()
        if evento == "partida_inicio":
            self.emitir(evento, partida_id=d["partida_id"], avisos=d.get("avisos", []),
                        equipos=[asdict(e) for e in d["equipos"]], vigilante=self.vigilante,
                        rondas=self.rondas, intentos=self.intentos)
            self.turnos_totales = self.rondas * len(d["equipos"])
        elif evento == "turno_inicio":
            t = d["tarjeta"]
            self.emitir(evento, equipo=d["equipo"], ronda=d["ronda"], secreta=t.secreta,
                        categoria=t.categoria, dificultad=t.dificultad, prohibidas=d["prohibidas"])
        elif evento == "turno_fin":
            r = d["registro"]
            self.emitir(evento, equipo=r.equipo, ronda=r.ronda, secreta=r.palabra_secreta,
                        resultado=r.resultado, puntuacion=r.puntuacion, tiempo=r.tiempo_total_s,
                        intentos=r.intentos_usados)
        elif evento == "marcador":
            m = d["marcador"]
            self.emitir(evento, **_marcador(m))
            self.turnos_jugados += 1
            if self.pausar and self.turnos_jugados < self.turnos_totales:  # sin pausa tras el último
                self.continuar.clear()
                self.emitir("esperando")
                while not self.continuar.wait(0.25):
                    if self.detener:
                        raise DetenerPartida()
        elif evento == "partida_fin":
            self.emitir(evento, estado=d["estado"], ruta=str(d["ruta"]), **_marcador(d["marcador"]))
        else:  # ronda_inicio, descripcion*, veredicto, infraccion, respuesta, error
            self.emitir(evento, **{k: v for k, v in d.items() if _serializable(v)})


def _marcador(m) -> dict:
    return {"clasificacion": m.clasificacion(), "puntos": m.puntos, "aciertos": m.aciertos,
            "infracciones": m.infracciones, "ganadores": m.ganadores()}


def _serializable(v) -> bool:
    try:
        json.dumps(v)
        return True
    except TypeError:
        return False


# ------------------------------------------------------------- aplicación
class AppGUI:
    def __init__(self, ruta_config: str | None = None, simulado: bool = False,
                 directorio_partidas: Path = GAMES_DIR):
        self.ruta_config = ruta_config
        self.simulado = simulado
        self.directorio_partidas = Path(directorio_partidas)
        self.sesion = SesionJuego()
        self.retardo_simulado = 0.7

    def _cliente(self, cfg):
        return SimulatedClient(semilla=cfg.ollama.seed or 0, p_trampa=0.25, retardo_s=self.retardo_simulado) if self.simulado else OllamaClient.desde_config(cfg)

    def estado(self) -> dict:
        cfg = cargar_config(self.ruta_config)
        datos = {
            "simulado": self.simulado,
            "partida_activa": self.sesion.activa,
            "config": {
                "equipos": [asdict(e) for e in cfg.equipos],
                "vigilante": cfg.vigilante,
                "usar_vigilante": cfg.juego.usar_vigilante_semantico,
                "rondas": cfg.juego.rondas,
                "num_prohibidas": cfg.juego.num_prohibidas,
                "intentos": cfg.juego.intentos_por_tarjeta,
                "max_prohibidas": MAX_PROHIBIDAS,
            },
        }
        if self.simulado:
            datos.update(ollama=True, modelos=cfg.modelos_necesarios(True), error=None)
            return datos
        cliente = self._cliente(cfg)
        estado = ModelManager(cliente).comprobar(cfg.modelos_necesarios())
        datos.update(ollama=estado.ollama_disponible,
                     modelos=[m for m in estado.instalados if not es_modelo_remoto(m)],
                     error=estado.error)
        return datos

    def iniciar_partida(self, peticion: dict) -> dict:
        if self.sesion.activa:
            raise ValueError("Ya hay una partida en curso")
        cfg = cargar_config(self.ruta_config)
        try:
            equipos = [TeamConfig(str(e["nombre"]).strip() or f"Equipo {i + 1}",
                                  str(e["descriptor"]), str(e["adivinador"]))
                       for i, e in enumerate(peticion.get("equipos") or [])]
        except (KeyError, TypeError) as e:
            raise ValueError("Formato de equipos incorrecto") from e
        if equipos:
            cfg.equipos = equipos
        cfg.vigilante = peticion.get("vigilante") or None
        cfg.juego.usar_vigilante_semantico = bool(cfg.vigilante)
        for clave, campo in (("rondas", "rondas"), ("num_prohibidas", "num_prohibidas"),
                             ("intentos", "intentos_por_tarjeta")):
            if peticion.get(clave) is not None:
                setattr(cfg.juego, campo, int(peticion[clave]))
        validar_config(cfg)

        cliente = self._cliente(cfg)
        if not self.simulado:
            gestor = ModelManager(cliente)
            estado = gestor.comprobar(cfg.modelos_necesarios())
            if not estado.todo_correcto:
                raise ValueError((estado.error or "Faltan modelos") + "\n" + gestor.instrucciones(estado))

        tarjetas = cargar_tarjetas(cfg.ruta_tarjetas(), estricto=False)
        sesion = SesionJuego()
        sesion.pausar = bool(peticion.get("pausar"))
        sesion.vigilante = cfg.vigilante
        sesion.rondas = cfg.juego.rondas
        sesion.intentos = cfg.juego.intentos_por_tarjeta
        sesion.activa = True
        self.sesion = sesion
        motor = MotorJuego(cfg, cliente, tarjetas, observador=sesion.observador,
                           directorio_partidas=self.directorio_partidas, simulado=self.simulado)

        modelos = cfg.modelos_necesarios()

        def ejecutar():
            try:
                sesion.emitir("carga_inicio", modelos=modelos)
                precargar(cliente, modelos, lambda ev, d: sesion.emitir(ev, **d))
                sesion.emitir("carga_fin")
                if sesion.detener:
                    sesion.emitir("fallo", mensaje="Partida cancelada durante la carga de modelos")
                    return
                motor.jugar_partida()
            except Exception as e:  # nunca dejar la web colgada
                sesion.emitir("fallo", mensaje=f"{type(e).__name__}: {e}")
            finally:
                sesion.activa = False

        sesion.hilo = threading.Thread(target=ejecutar, daemon=True)
        sesion.hilo.start()
        return {"ok": True}


# ------------------------------------------------------------------- HTTP
def crear_manejador(app: AppGUI):
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencio en consola
            pass

        def _json(self, datos, estado=HTTPStatus.OK):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(estado)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _error(self, mensaje, estado=HTTPStatus.BAD_REQUEST):
            self._json({"ok": False, "error": mensaje}, estado)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    cuerpo = (STATIC / "index.html").read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                elif url.path == "/api/estado":
                    self._json(app.estado())
                elif url.path == "/api/eventos":
                    n = int(q.get("desde", ["0"])[0])
                    self._json({"eventos": app.sesion.desde(n), "activa": app.sesion.activa})
                elif url.path == "/api/historial":
                    self._json({"partidas": listar_partidas(app.directorio_partidas)})
                elif url.path == "/api/partida":
                    self._json(cargar_partida(q.get("id", [""])[0], app.directorio_partidas))
                else:
                    self._error("No encontrado", HTTPStatus.NOT_FOUND)
            except FileNotFoundError as e:
                self._error(str(e), HTTPStatus.NOT_FOUND)
            except (ConfigError, ValueError) as e:
                self._error(str(e))

        def do_POST(self):
            url = urlparse(self.path)
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
            except (ValueError, json.JSONDecodeError):
                return self._error("JSON inválido")
            try:
                if url.path == "/api/partida":
                    self._json(app.iniciar_partida(cuerpo))
                elif url.path == "/api/continuar":
                    app.sesion.continuar.set()
                    self._json({"ok": True})
                elif url.path == "/api/detener":
                    app.sesion.detener = True
                    app.sesion.continuar.set()
                    self._json({"ok": True})
                elif url.path == "/api/pausa":
                    app.sesion.pausar = bool(cuerpo.get("pausar"))
                    if not app.sesion.pausar:
                        app.sesion.continuar.set()
                    self._json({"ok": True})
                else:
                    self._error("No encontrado", HTTPStatus.NOT_FOUND)
            except (ConfigError, ValueError) as e:
                self._error(str(e))

    return Manejador


def crear_servidor(app: AppGUI, puerto: int = 8765) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), crear_manejador(app))
    servidor.daemon_threads = True
    return servidor


def lanzar(ruta_config: str | None = None, simulado: bool = False, puerto: int = 8765,
           abrir_navegador: bool = True) -> None:
    app = AppGUI(ruta_config, simulado)
    try:
        servidor = crear_servidor(app, puerto)
    except OSError:
        print(f"El puerto {puerto} está ocupado. Prueba con: python main.py gui --puerto {puerto + 1}")
        return
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Interfaz gráfica en {url}  (Ctrl+C para cerrar)")
    if simulado:
        print("⚠ MODO SIMULADO: no se usan modelos reales.")
    if abrir_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando la interfaz gráfica.")
    finally:
        app.sesion.detener = True
        app.sesion.continuar.set()
        servidor.server_close()
