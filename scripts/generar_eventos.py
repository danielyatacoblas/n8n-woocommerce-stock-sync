#!/usr/bin/env python3
"""Genera un día de avisos de WooCommerce, firmados como los firma la tienda.

    python scripts/generar_eventos.py

Salida: data/eventos.json, una lista de avisos en orden con
  descripcion     qué representa el aviso
  tipo_contenido  cabecera Content-Type con la que llega
  cuerpo          el JSON exacto que manda WooCommerce (texto, no objeto)
  firma           cabecera X-WC-Webhook-Signature
  esperado        acción que debe tomar el flujo

Los avisos están escritos a mano, uno por cada situación que un flujo
ingenuo maneja mal: reintentos, cancelaciones de pedidos no pagados,
sobreventa, SKU desconocido, firma falsa y cuerpo alterado después de firmar.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync_tienda import firmar  # noqa: E402

SECRETO_DEMO = "clave-demo-no-usar-en-produccion"
SALIDA = ROOT / "data" / "eventos.json"


def pedido(pid: int, status: str, lineas: list[tuple[str, int]], hora: str) -> dict:
    return {
        "id": pid, "number": str(pid), "status": status, "currency": "PEN",
        "date_modified": f"2026-09-10T{hora}:00",
        "billing": {"first_name": "Cliente", "last_name": f"Demo {pid}"},
        "line_items": [{"id": pid * 10 + i, "name": sku or "Producto sin SKU",
                        "sku": sku, "quantity": cant}
                       for i, (sku, cant) in enumerate(lineas)],
    }


def aviso(descripcion: str, cuerpo: str, esperado: str, firma: str | None = None,
          tipo: str = "application/json") -> dict:
    return {"descripcion": descripcion, "tipo_contenido": tipo, "cuerpo": cuerpo,
            "firma": firma if firma is not None else firmar(cuerpo, SECRETO_DEMO),
            "esperado": esperado}


def js(p: dict) -> str:
    return json.dumps(p, ensure_ascii=False)


def main():
    p1001 = pedido(1001, "processing", [("CAF-VRS-250", 2), ("PRE-V60", 1)], "09:05")
    p1002 = pedido(1002, "processing", [("CAF-CUS-250", 4)], "09:40")
    alterado = js(pedido(1010, "processing", [("CAF-VRS-1K", 1)], "18:00"))

    eventos = [
        aviso("WooCommerce prueba el webhook al crearlo", "webhook_id=7", "ignorado",
              tipo="application/x-www-form-urlencoded"),
        aviso("#1001 creado, todavía sin pagar",
              js(pedido(1001, "pending", [("CAF-VRS-250", 2), ("PRE-V60", 1)], "09:00")),
              "ignorado"),
        aviso("#1001 pagado", js(p1001), "descontar"),
        aviso("#1001 reintento del mismo aviso (WooCommerce no recibió respuesta)",
              js(p1001), "ignorado"),
        aviso("#1002 pagado: el geisha baja del mínimo", js(p1002), "descontar"),
        aviso("#1003 pagado: se venden las 3 últimas tazas",
              js(pedido(1003, "processing", [("ACC-TAZA", 3)], "10:15")), "descontar"),
        aviso("#1004 pagado: una taza más de las que había",
              js(pedido(1004, "processing", [("ACC-TAZA", 1)], "10:20")), "descontar"),
        aviso("#1004 cancelado: la taza vuelve al stock",
              js(pedido(1004, "cancelled", [("ACC-TAZA", 1)], "10:45")), "devolver"),
        aviso("#1005 cancelado sin haber pagado nunca",
              js(pedido(1005, "cancelled", [("CAF-DES-250", 2)], "11:00")), "ignorado"),
        aviso("#1006 pagado con un SKU que no existe y un producto sin SKU",
              js(pedido(1006, "processing",
                        [("CAF-CHA-250", 2), ("CAF-XYZ", 1), ("", 1)], "11:30")),
              "descontar"),
        aviso("#1007 falso: alguien descubrió la URL del webhook",
              js(pedido(1007, "processing", [("CAF-VRS-1K", 10)], "12:00")),
              "rechazado", firma="Zm9ybWFmYWxzYQ=="),
        aviso("#1001 entregado: no vuelve a descontar",
              js(pedido(1001, "completed", [("CAF-VRS-250", 2), ("PRE-V60", 1)], "15:00")),
              "ignorado"),
        aviso("#1003 reembolsado: vuelven las 3 tazas",
              js(pedido(1003, "refunded", [("ACC-TAZA", 3)], "16:00")), "devolver"),
        aviso("#1008 en espera de transferencia",
              js(pedido(1008, "on-hold", [("PRE-PRENSA", 1)], "16:30")), "ignorado"),
        aviso("#1009 pagado: 5 kits cuando quedan 4",
              js(pedido(1009, "processing", [("KIT-REGALO", 5)], "17:00")), "descontar"),
        aviso("#1002 reenviado con otro formato de JSON (misma información)",
              json.dumps(p1002, ensure_ascii=False, indent=1), "ignorado"),
        aviso("#1010 alterado después de firmar: cambiaron la cantidad",
              alterado.replace('"quantity": 1', '"quantity": 50'), "rechazado",
              firma=firmar(alterado, SECRETO_DEMO)),
    ]
    SALIDA.write_text(json.dumps(eventos, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"{len(eventos)} avisos en {SALIDA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
