"""Tabú entre modelos locales — punto de entrada.

Uso rápido:
    python main.py                      # menú interactivo
    python main.py gui                  # interfaz gráfica en el navegador
    python main.py modelos              # comprobar Ollama y modelos
    python main.py demo                 # demostración guiada para clase
    python main.py jugar --rondas 2     # partida con la configuración de config.json
    python main.py historial [ID]       # consultar partidas guardadas
    python main.py experimento          # experimento 3 / 5 / 7 prohibidas
    python main.py analizar CARPETA     # recalcular estadísticas y gráficos
    python main.py tarjetas validar     # revisar el mazo
    python main.py tarjetas generar -n 5 --modelo qwen2.5:3b

Añade --simulado a jugar/demo/experimento para probar sin Ollama (resultados
SINTÉTICOS, solo para comprobar que el programa funciona).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cards.card_generator import CardGenerator, guardar_generadas
from cards.card_validator import validar_mazo
from cards.deck import TarjetasInvalidasError, cargar_tarjetas, leer_json_tarjetas
from config import CARDS_DIR, ConfigError, Config, TeamConfig, cargar_config
from experiment.experiment_runner import EjecutorExperimento, analizar, estimar_duracion
from game.game_engine import MotorJuego
from game.game_logger import cargar_partida, listar_partidas
from models.fake_client import SimulatedClient
from models.model_manager import ModelManager, precargar
from models.ollama_client import OllamaClient
from ui import console as ui


# ---------------------------------------------------------------- utilidades
def crear_cliente(cfg: Config, simulado: bool):
    if simulado:
        print(ui.amarillo("⚠ MODO SIMULADO: no se usan modelos reales; los resultados son sintéticos."))
        return SimulatedClient(semilla=cfg.ollama.seed or 0)
    return OllamaClient.desde_config(cfg)


def comprobar_modelos(cfg: Config, client, mostrar: bool = True) -> bool:
    gestor = ModelManager(client)
    estado = gestor.comprobar(cfg.modelos_necesarios())
    if mostrar:
        ui.titulo("Comprobación de Ollama y modelos")
        print(f"  Ollama: {ui.verde('disponible') if estado.ollama_disponible else ui.rojo('NO disponible')}"
              f"  ({cfg.ollama.host})")
        if estado.instalados:
            print("  Modelos instalados: " + ", ".join(estado.instalados))
        for m in cfg.modelos_necesarios():
            ok = m not in estado.faltan and m not in estado.remotos
            print(f"   {'✔' if ok else '✖'} {m}")
    if not estado.todo_correcto:
        print(ui.amarillo("\n" + (estado.error + "\n" if estado.error else "") + gestor.instrucciones(estado)))
    return estado.todo_correcto


def cargar_mazo(cfg: Config):
    try:
        return cargar_tarjetas(cfg.ruta_tarjetas(), estricto=False)
    except (OSError, ValueError) as e:
        print(ui.rojo(f"No se pudieron cargar las tarjetas: {e}"))
        sys.exit(1)


def aplicar_overrides(cfg: Config, args) -> None:
    if getattr(args, "rondas", None):
        cfg.juego.rondas = args.rondas
    if getattr(args, "prohibidas", None):
        cfg.juego.num_prohibidas = args.prohibidas
    if getattr(args, "intentos", None):
        cfg.juego.intentos_por_tarjeta = args.intentos
    if getattr(args, "sin_vigilante", False):
        cfg.juego.usar_vigilante_semantico = False


# ------------------------------------------------------------------ comandos
def cmd_modelos(cfg: Config, args) -> int:
    try:
        client = OllamaClient.desde_config(cfg)
    except ValueError as e:
        print(ui.rojo(str(e)))
        return 1
    return 0 if comprobar_modelos(cfg, client) else 1


def cmd_jugar(cfg: Config, args, pausar: bool = False) -> int:
    aplicar_overrides(cfg, args)
    client = crear_cliente(cfg, args.simulado)
    if not args.simulado and not comprobar_modelos(cfg, client, mostrar=False):
        return 1
    if not args.simulado:
        print(ui.gris("Cargando modelos en memoria (solo la primera vez tarda)…"))
        for r in precargar(client, cfg.modelos_necesarios()):
            estado = ui.verde("listo") if r["ok"] else ui.rojo(f"error: {r['error']}")
            print(f"  {r['modelo']}: {estado} ({r['tiempo']} s)")
    motor = MotorJuego(cfg, client, cargar_mazo(cfg),
                       observador=ui.PresentadorPartida(pausar=pausar), simulado=args.simulado)
    resultado = motor.jugar_partida()
    for a in resultado.avisos:
        if "abortada" in a:
            print(ui.rojo(a))
    return 0 if resultado.estado in ("terminada", "mazo_agotado") else 1


def _elegir_modelo(rol: str, instalados: list[str], actual: str) -> str:
    defecto = instalados.index(actual) if actual in instalados else 0
    print(f"\n{ui.negrita(rol)}")
    return instalados[ui.pedir_opcion("Elige modelo", instalados, defecto)]


def cmd_demo(cfg: Config, args) -> int:
    ui.titulo("TABÚ ENTRE MODELOS LOCALES · Modo demostración")
    print("  Tres roles: el DESCRIPTOR ve la palabra y las prohibidas; el ADIVINADOR solo ve las\n"
          "  pistas; el VIGILANTE revisa trampas. El programa (árbitro) reparte la información,\n"
          "  detecta infracciones y lleva el marcador.\n")
    aplicar_overrides(cfg, args)
    client = crear_cliente(cfg, args.simulado)

    # 1. Comprobar modelos disponibles
    if not args.simulado:
        gestor = ModelManager(client)
        estado = gestor.comprobar(cfg.modelos_necesarios())
        if not estado.ollama_disponible:
            print(ui.rojo("Ollama no está disponible.\n") + gestor.instrucciones(estado))
            return 1
        instalados = [m for m in estado.instalados if not m.endswith("-cloud")]
        if not instalados:
            print(ui.rojo("No hay modelos instalados. Ejemplo: ollama pull llama3.2:3b"))
            return 1
        print("  Modelos locales disponibles: " + ", ".join(instalados))
        # 2. Selección de modelos
        if estado.faltan or input("\n¿Cambiar los modelos de config.json? (s/N): ").strip().lower() == "s":
            n_eq = 1 if len(instalados) == 1 else len(cfg.equipos)
            equipos = []
            for i in range(n_eq):
                base = cfg.equipos[i] if i < len(cfg.equipos) else cfg.equipos[0]
                d = _elegir_modelo(f"{base.nombre} · descriptor", instalados, base.descriptor)
                a = _elegir_modelo(f"{base.nombre} · adivinador", instalados, base.adivinador)
                equipos.append(TeamConfig(base.nombre, d, a))
            cfg.equipos = equipos
            opciones = ["(sin vigilante: solo detector automático)"] + instalados
            actual = opciones.index(cfg.vigilante) if cfg.vigilante in opciones else 0
            print(f"\n{ui.negrita('Vigilante')}")
            elegido = opciones[ui.pedir_opcion("Elige modelo", opciones, actual)]
            cfg.vigilante = None if elegido.startswith("(") else elegido
            cfg.juego.usar_vigilante_semantico = cfg.vigilante is not None
    # 3-8. Partida con presentación paso a paso
    return cmd_jugar(cfg, args, pausar=not args.sin_pausa)


def cmd_historial(cfg: Config, args) -> int:
    if args.partida:
        try:
            ui.mostrar_partida(cargar_partida(args.partida))
        except FileNotFoundError as e:
            print(ui.rojo(str(e)))
            return 1
    else:
        ui.mostrar_historial(listar_partidas())
        print(ui.gris("\n  Detalle: python main.py historial <ID o prefijo>"))
    return 0


def cmd_experimento(cfg: Config, args) -> int:
    if args.tarjetas:
        cfg.experimento.num_tarjetas = args.tarjetas
    if args.repeticiones:
        cfg.experimento.repeticiones = args.repeticiones
    if args.sin_vigilante:
        cfg.juego.usar_vigilante_semantico = False
    client = crear_cliente(cfg, args.simulado)
    if not args.simulado and not comprobar_modelos(cfg, client):
        return 1
    try:
        tarjetas = cargar_tarjetas(cfg.ruta_tarjetas(), estricto=True)
    except TarjetasInvalidasError as e:
        print(ui.rojo(str(e)))
        return 1
    ejecutor = EjecutorExperimento(cfg, client, tarjetas, simulado=args.simulado,
                                   progreso=lambda i, n, r: print(
                                       f"  [{i}/{n}] {r.equipo:<12} n={r.num_prohibidas} "
                                       f"{r.palabra_secreta:<12} {r.resultado:<10} {r.puntuacion:+d}"))
    total = ejecutor.total_turnos()
    ui.titulo("Experimento: número de palabras prohibidas")
    print(f"  Condiciones {cfg.experimento.condiciones} · {len(ejecutor.tarjetas)} tarjetas · "
          f"{len(cfg.equipos)} equipos · {cfg.experimento.repeticiones} repeticiones = {total} turnos")
    if not args.simulado:
        print(f"  Duración orientativa: {estimar_duracion(total):.1f} h (muy dependiente del hardware)")
        if not args.si and input("¿Lanzar? (s/N): ").strip().lower() != "s":
            return 0
    try:
        carpeta = ejecutor.ejecutar(reanudar=args.reanudar)
    except (RuntimeError, KeyboardInterrupt) as e:
        print(ui.rojo(f"\n{e or 'Interrumpido'}"))
        return 1
    print(ui.verde(f"\nResultados en {carpeta}"))
    print("  " + "\n  ".join(p.name for p in sorted(carpeta.iterdir())))
    return 0


def cmd_analizar(cfg: Config, args) -> int:
    rutas = analizar(Path(args.carpeta), semilla=cfg.experimento.semilla)
    for k, v in rutas.items():
        print(f"  {k}: {v}")
    return 0


def cmd_tarjetas(cfg: Config, args) -> int:
    if args.accion == "validar":
        crudas = []
        for r in cfg.ruta_tarjetas():
            if r.exists():
                crudas += leer_json_tarjetas(r)
        resultados, globales = validar_mazo(crudas)
        malas = [r for r in resultados if not r.valida]
        con_avisos = [r for r in resultados if r.avisos]
        ui.titulo("Validación de tarjetas")
        print(f"  {len(resultados)} tarjetas · {len(resultados) - len(malas)} válidas · {len(malas)} inválidas")
        for r in malas:
            print(ui.rojo(f"  ✖ {r.id}: {'; '.join(r.errores)}"))
        for r in con_avisos:
            print(ui.amarillo(f"  ⚠ {r.id}: {'; '.join(r.avisos)}"))
        for g in globales:
            print(ui.rojo(f"  ✖ {g}"))
        return 1 if malas or globales else 0

    # generar
    client = OllamaClient.desde_config(cfg)
    modelo = args.modelo or cfg.equipos[0].descriptor
    existentes = [t.secreta for t in cargar_mazo(cfg)]
    gen = CardGenerator(client, modelo, modelo_revisor=args.revisor or cfg.vigilante)
    informe = gen.generar(args.n, existentes, categorias=[args.categoria] if args.categoria else None)
    for t in informe.aceptadas:
        print(ui.verde(f"  ✔ {t['secreta']}: {', '.join(t['prohibidas'] + t['prohibidas_extra'])}"))
    for t, problemas in informe.rechazadas:
        nombre = t["secreta"] if t else "?"
        print(ui.amarillo(f"  ✖ {nombre}: {'; '.join(problemas)}"))
    if informe.aceptadas:
        destino = CARDS_DIR / "cards_generadas.json"
        guardar_generadas(informe.aceptadas, destino)
        print(f"\n  Guardadas en {destino}. Revísalas y añade el fichero a 'ficheros_tarjetas' para usarlas.")
    return 0


def cmd_gui(cfg: Config, args) -> int:
    from gui.server import lanzar
    lanzar(getattr(args, "config", None), simulado=args.simulado, puerto=args.puerto,
           abrir_navegador=not args.no_abrir)
    return 0


def menu(cfg_path: str | None) -> int:
    opciones = ["Comprobar modelos", "Demostración guiada", "Jugar partida rápida",
                "Historial de partidas", "Validar tarjetas", "Experimento",
                "Interfaz gráfica (navegador)", "Salir"]
    while True:
        ui.titulo("TABÚ ENTRE MODELOS LOCALES")
        i = ui.pedir_opcion("Opción", opciones, 1)
        cfg = cargar_config(cfg_path)
        ns = argparse.Namespace(simulado=False, sin_pausa=False, rondas=None, prohibidas=None,
                                intentos=None, sin_vigilante=False, partida=None, accion="validar",
                                tarjetas=None, repeticiones=None, reanudar=None, si=False,
                                config=cfg_path, puerto=8765, no_abrir=False)
        acciones = [cmd_modelos, cmd_demo, cmd_jugar, cmd_historial, cmd_tarjetas, cmd_experimento, cmd_gui]
        if i == len(opciones) - 1:
            return 0
        try:
            acciones[i](cfg, ns)
        except KeyboardInterrupt:
            print(ui.amarillo("\nCancelado."))
        ui.pausa(True, "\nPulsa Enter para volver al menú...")


# ---------------------------------------------------------------------- CLI
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tabú entre modelos de lenguaje locales (Ollama)")
    p.add_argument("--config", help="Ruta a un config.json alternativo")
    sub = p.add_subparsers(dest="comando")

    sub.add_parser("modelos", help="Comprobar Ollama y los modelos de la configuración")

    s = sub.add_parser("gui", help="Interfaz gráfica en el navegador")
    s.add_argument("--simulado", action="store_true", help="Sin Ollama, datos sintéticos")
    s.add_argument("--puerto", type=int, default=8765)
    s.add_argument("--no-abrir", action="store_true", help="No abrir el navegador automáticamente")

    for nombre, ayuda in (("jugar", "Jugar una partida"), ("demo", "Demostración guiada para clase")):
        s = sub.add_parser(nombre, help=ayuda)
        s.add_argument("--rondas", type=int)
        s.add_argument("--prohibidas", type=int, help="Número de palabras prohibidas (1-7)")
        s.add_argument("--intentos", type=int, help="Intentos por tarjeta")
        s.add_argument("--sin-vigilante", action="store_true", help="Solo detector automático")
        s.add_argument("--simulado", action="store_true", help="Sin Ollama, datos sintéticos")
        s.add_argument("--sin-pausa", action="store_true", help="No esperar Enter entre turnos")

    s = sub.add_parser("historial", help="Ver partidas guardadas")
    s.add_argument("partida", nargs="?", help="ID (o prefijo) de una partida para ver el detalle")

    s = sub.add_parser("experimento", help="Experimento 3/5/7 palabras prohibidas")
    s.add_argument("--tarjetas", type=int, help="Número de tarjetas")
    s.add_argument("--repeticiones", type=int)
    s.add_argument("--reanudar", help="ID de un experimento interrumpido")
    s.add_argument("--sin-vigilante", action="store_true")
    s.add_argument("--simulado", action="store_true")
    s.add_argument("--si", action="store_true", help="No pedir confirmación")

    s = sub.add_parser("analizar", help="Recalcular estadísticas y gráficos de un experimento")
    s.add_argument("carpeta")

    s = sub.add_parser("tarjetas", help="Validar o generar tarjetas")
    s.add_argument("accion", choices=["validar", "generar"])
    s.add_argument("-n", type=int, default=5, help="Tarjetas a generar")
    s.add_argument("--modelo", help="Modelo generador")
    s.add_argument("--revisor", help="Modelo revisor (por defecto, el vigilante)")
    s.add_argument("--categoria")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        if not args.comando:
            return menu(args.config)
        cfg = cargar_config(args.config)
        comandos = {"gui": cmd_gui, "modelos": cmd_modelos, "jugar": cmd_jugar, "demo": cmd_demo,
                    "historial": cmd_historial, "experimento": cmd_experimento,
                    "analizar": cmd_analizar, "tarjetas": cmd_tarjetas}
        return comandos[args.comando](cfg, args)
    except ConfigError as e:
        print(ui.rojo(str(e)))
        return 2
    except KeyboardInterrupt:
        print(ui.amarillo("\nInterrumpido."))
        return 130


if __name__ == "__main__":
    sys.exit(main())
