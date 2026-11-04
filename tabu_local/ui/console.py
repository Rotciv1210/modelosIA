"""Interfaz de consola: colores, presentación de eventos de partida e historial.

Sin dependencias externas. Los colores ANSI se desactivan automáticamente si la
salida no es una terminal o si existe la variable de entorno NO_COLOR.
"""
from __future__ import annotations

import os
import sys

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if os.name == "nt":  # habilita ANSI en terminales de Windows modernas
    os.system("")


def _c(codigo: str, texto: str) -> str:
    return f"\033[{codigo}m{texto}\033[0m" if _COLOR else texto


def negrita(t): return _c("1", t)
def verde(t): return _c("32", t)
def rojo(t): return _c("31", t)
def amarillo(t): return _c("33", t)
def azul(t): return _c("34", t)
def gris(t): return _c("90", t)


def titulo(texto: str) -> None:
    print("\n" + negrita("═" * 64))
    print(negrita(f"  {texto}"))
    print(negrita("═" * 64))


def pausa(activa: bool, mensaje: str = "Pulsa Enter para continuar...") -> None:
    if activa:
        try:
            input(gris(mensaje))
        except EOFError:
            pass


def pedir_opcion(pregunta: str, opciones: list[str], defecto: int = 0) -> int:
    for i, o in enumerate(opciones, 1):
        marca = gris(" (por defecto)") if i - 1 == defecto else ""
        print(f"  {i}) {o}{marca}")
    while True:
        try:
            r = input(f"{pregunta} [{defecto + 1}]: ").strip()
        except EOFError:
            return defecto
        if not r:
            return defecto
        if r.isdigit() and 1 <= int(r) <= len(opciones):
            return int(r) - 1
        print(rojo("Opción no válida"))


class PresentadorPartida:
    """Observador que muestra en directo lo que ocurre en la partida."""

    def __init__(self, pausar: bool = False, mostrar_vigilante: bool = True):
        self.pausar = pausar
        self.mostrar_vigilante = mostrar_vigilante

    def __call__(self, evento: str, d: dict) -> None:
        metodo = getattr(self, f"_{evento}", None)
        if metodo:
            metodo(d)

    def _partida_inicio(self, d):
        titulo(f"Nueva partida · {d['partida_id']}")
        for eq in d["equipos"]:
            print(f"  {negrita(eq.nombre)}: describe {azul(eq.descriptor)} · adivina {azul(eq.adivinador)}")
        for a in d.get("avisos", []):
            print(amarillo(f"  ⚠ {a}"))

    def _ronda_inicio(self, d):
        print("\n" + negrita(f"────────────── RONDA {d['ronda']} ──────────────"))

    def _turno_inicio(self, d):
        t = d["tarjeta"]
        print(f"\n▶ Turno de {negrita(d['equipo'])}  ({t.categoria}, {t.dificultad})")
        print(f"  Palabra secreta (solo la ve el público y el descriptor): {negrita(t.secreta.upper())}")
        print(f"  Prohibidas: {', '.join(d['prohibidas'])}")
        pausa(self.pausar)

    def _descripcion_generada(self, d):
        print(f"  🗣  Descriptor (pista {d['intento']}): {azul(d['texto'])}")

    def _descripcion(self, d):
        print(gris("     ✔ pista revisada y entregada al adivinador"))

    def _descripcion_invalida(self, d):
        texto = (d.get("texto") or "").strip().replace("\n", " ")[:80]
        print(amarillo(f"  ↻ Descripción inválida ({d['motivo']}), se pide otra. ") + gris(texto))

    def _veredicto(self, d):
        if not self.mostrar_vigilante:
            return
        v = d["veredicto"]
        if not v.get("valido", True):
            print(gris("  👁  Vigilante: sin veredicto válido (no penaliza)"))
        elif v.get("descartado_por_arbitro"):
            print(gris(f"  👁  Vigilante: sospecha descartada por el árbitro ({v['descartado_por_arbitro']})"))
        elif v["infraccion"]:
            print(amarillo(f"  👁  Vigilante: posible trampa ({v['tipo_infraccion']}, "
                           f"confianza {v['nivel_confianza']:.2f}) — {v['justificacion']}"))
        else:
            print(gris(f"  👁  Vigilante: sin infracciones (confianza {v['nivel_confianza']:.2f})"))

    def _infraccion(self, d):
        print(rojo("  ✖ INFRACCIÓN: la pista NO se entrega al adivinador"))
        for i in d["infracciones"]:
            print(rojo(f"     - [{i['origen']}/{i['tipo']}] {i.get('justificacion', '')}"))

    def _respuesta(self, d):
        r = d["respuesta"] or "(sin respuesta válida)"
        if d["acierto"]:
            print(verde(f"  🎯 Adivinador: «{r}» → ¡CORRECTO!"))
        else:
            print(f"  🤔 Adivinador: «{r}» → incorrecto")

    def _error(self, d):
        print(rojo(f"  ⚠ Error: {d['mensaje']}"))

    def _turno_fin(self, d):
        r = d["registro"]
        signo = "+" if r.puntuacion > 0 else ""
        print(f"  Resultado: {negrita(r.resultado.upper())} · puntos {signo}{r.puntuacion} "
              f"· {r.tiempo_total_s:.1f} s")

    def _marcador(self, d):
        m = d["marcador"]
        print(gris("  Marcador: " + " | ".join(f"{e} {p}" for e, p in m.clasificacion())))
        pausa(self.pausar)

    def _partida_fin(self, d):
        m = d["marcador"]
        titulo("Fin de la partida")
        for pos, (e, p) in enumerate(m.clasificacion(), 1):
            print(f"  {pos}. {negrita(e)}: {p} puntos · {m.aciertos[e]} aciertos · "
                  f"{m.infracciones[e]} infracciones")
        g = m.ganadores()
        if len(g) == 1:
            print(verde(negrita(f"\n  🏆 Gana {g[0]}")))
        else:
            print(amarillo(negrita(f"\n  🤝 Empate entre {', '.join(g)}")))
        if d.get("estado") != "terminada":
            print(amarillo(f"  (estado: {d['estado']})"))
        print(gris(f"  Registro guardado en {d['ruta']}"))


def mostrar_historial(resumenes: list[dict]) -> None:
    if not resumenes:
        print("Todavía no hay partidas guardadas.")
        return
    titulo("Historial de partidas")
    for r in resumenes:
        puntos = ", ".join(f"{e}: {p}" for e, p in r["puntos"].items())
        sim = amarillo(" [SIMULADA]") if r.get("simulado") else ""
        print(f"  {negrita(r['partida_id'])}{sim}  {r['inicio']}  {r['estado']}  "
              f"{r['turnos']} turnos  ·  {puntos}  ·  ganador: {', '.join(r['ganadores']) or '-'}")


def mostrar_partida(d: dict) -> None:
    titulo(f"Partida {d['partida_id']}" + ("  [SIMULADA]" if d.get("simulado") else ""))
    print(f"  Inicio {d['inicio']} · fin {d['fin']} · estado {d['estado']}")
    for t in d["turnos"]:
        print(f"\n  Ronda {t['ronda']} · {negrita(t['equipo'])} · secreta {negrita(t['palabra_secreta'])} "
              f"· prohibidas: {', '.join(t['palabras_prohibidas'])}")
        print(gris(f"    descriptor {t['modelo_descriptor']} · adivinador {t['modelo_adivinador']} "
                   f"· vigilante {t['modelo_vigilante']}"))
        for i, desc in enumerate(t["descripciones"], 1):
            resp = t["respuestas_adivinador"][i - 1] if i - 1 < len(t["respuestas_adivinador"]) else "-"
            print(f"    pista {i}: {desc}")
            print(f"       → {resp}")
        for i in t["infracciones"]:
            print(rojo(f"    infracción [{i['origen']}/{i['tipo']}]: {i.get('justificacion')}"))
        for e in t["errores"]:
            print(amarillo(f"    {e}"))
        print(f"    Resultado: {t['resultado']} · puntos {t['puntuacion']} · {t['tiempo_total_s']} s")
    m = d.get("marcador") or {}
    if m:
        print("\n  Marcador final: " + ", ".join(f"{e}: {p}" for e, p in m["puntos"].items())
              + f" · ganador: {', '.join(m['ganadores'])}")
