#!/usr/bin/env python3
"""Pasa el día de avisos por el flujo y muestra qué hizo con cada uno.

    python scripts/generar_eventos.py
    python scripts/simular_dia.py

Imprime la decisión por aviso, las alertas, el kardex y el stock final, y
avisa si alguna decisión no coincide con la esperada.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync_tienda import (firma_valida, inventario_desde_filas,  # noqa: E402
                             procesar_evento)

SECRETO_DEMO = "clave-demo-no-usar-en-produccion"
INVENTARIO = ROOT / "data" / "inventario.json"
EVENTOS = ROOT / "data" / "eventos.json"


def simular() -> tuple[list[dict], dict, dict]:
    if not EVENTOS.exists():
        raise SystemExit("Primero corre: python scripts/generar_eventos.py")
    productos = json.loads(INVENTARIO.read_text(encoding="utf-8"))["productos"]
    inicial = inventario_desde_filas(productos)
    estado = {"inventario": inventario_desde_filas(productos)}
    resultados = []
    for e in json.loads(EVENTOS.read_text(encoding="utf-8")):
        ok = firma_valida(e["cuerpo"], e["firma"], SECRETO_DEMO)
        r = procesar_evento(e["cuerpo"], ok, estado, "2026-09-10T00:00:00")
        resultados.append(dict(r, descripcion=e["descripcion"], esperado=e["esperado"]))
    return resultados, inicial, estado


def main():
    resultados, inicial, estado = simular()
    print("Avisos:")
    for r in resultados:
        marca = "  " if r["accion"] == r["esperado"] else "!!"
        detalle = r["motivo"] or ", ".join(f"{m['sku']} {m['cantidad']:+d}" for m in r["movimientos"])
        print(f"{marca} {r['accion']:<10} {r['descripcion']}\n{'':14}{detalle}")

    print("\nAlertas al equipo:")
    for r in resultados:
        for a in r["alertas"]:
            print(f"  [{a['tipo']}] {a['mensaje']}")

    print("\nStock que cambió:")
    for sku, p in estado["inventario"].items():
        antes = inicial[sku]["stock"]
        if p["stock"] != antes:
            print(f"  {sku:<12} {antes:>3} → {p['stock']:>3}  {p['nombre']}")

    fallos = [r for r in resultados if r["accion"] != r["esperado"]]
    print(f"\nDecisiones correctas: {len(resultados) - len(fallos)}/{len(resultados)}")


if __name__ == "__main__":
    main()
