"""Tests de la sincronización de stock."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync_tienda import (entero, firma_valida, firmar,  # noqa: E402
                             inventario_desde_filas, procesar_evento)

SECRETO = "secreto-de-prueba"


def tienda(**stock):
    filas = [{"sku": "CAFE", "nombre": "Café 250 g", "stock": 10, "minimo": 3, "product_id": 1},
             {"sku": "TAZA", "nombre": "Taza", "stock": 2, "minimo": 1, "product_id": 2}]
    for f in filas:
        if f["sku"] in stock:
            f["stock"] = stock[f["sku"]]
    return {"inventario": inventario_desde_filas(filas)}


def aviso(estado, pid, status, **lineas):
    cuerpo = json.dumps({"id": pid, "status": status,
                         "line_items": [{"sku": s, "quantity": q, "name": s} for s, q in lineas.items()]})
    return procesar_evento(cuerpo, True, estado, "2026-09-10T10:00:00")


def stock(estado, sku):
    return estado["inventario"][sku]["stock"]


# ── firma ──────────────────────────────────────────────────────────────────

def test_firma_correcta():
    assert firma_valida('{"id":1}', firmar('{"id":1}', SECRETO), SECRETO)


@pytest.mark.parametrize("cuerpo,firma,secreto", [
    ('{"id":1}', firmar('{"id":1}', "otro"), SECRETO),          # otra clave
    ('{"id": 1}', firmar('{"id":1}', SECRETO), SECRETO),        # un espacio de diferencia
    ('{"id":1}', "", SECRETO),                                  # sin cabecera
    ('{"id":1}', firmar('{"id":1}', ""), ""),                   # secreto sin configurar
])
def test_firma_invalida(cuerpo, firma, secreto):
    assert not firma_valida(cuerpo, firma, secreto)


def test_aviso_con_firma_invalida_no_toca_el_stock():
    e = tienda()
    r = procesar_evento('{"id": 1, "status": "processing", "line_items": '
                        '[{"sku": "CAFE", "quantity": 5}]}', False, e, "")
    assert (r["accion"], r["http"]) == ("rechazado", 401)
    assert stock(e, "CAFE") == 10


# ── movimientos ────────────────────────────────────────────────────────────

def test_pedido_pagado_descuenta():
    e = tienda()
    r = aviso(e, 1, "processing", CAFE=2, TAZA=1)
    assert r["accion"] == "descontar"
    assert (stock(e, "CAFE"), stock(e, "TAZA")) == (8, 1)
    assert r["actualizar_tienda"] == [{"sku": "CAFE", "product_id": 1, "stock": 8},
                                      {"sku": "TAZA", "product_id": 2, "stock": 1}]


def test_el_mismo_pedido_no_descuenta_dos_veces():
    e = tienda()
    aviso(e, 1, "processing", CAFE=2)
    r = aviso(e, 1, "processing", CAFE=2)
    assert r["accion"] == "ignorado" and stock(e, "CAFE") == 8


def test_pagado_y_luego_completado_descuenta_una_sola_vez():
    e = tienda()
    aviso(e, 1, "processing", CAFE=2)
    aviso(e, 1, "completed", CAFE=2)
    assert stock(e, "CAFE") == 8


def test_cancelado_despues_de_pagar_devuelve():
    e = tienda()
    aviso(e, 1, "processing", CAFE=2)
    r = aviso(e, 1, "cancelled", CAFE=2)
    assert r["accion"] == "devolver" and stock(e, "CAFE") == 10


def test_cancelado_sin_haber_pagado_no_suma_stock():
    """Sin esta regla, cancelar pedidos impagos inflaría el inventario."""
    e = tienda()
    r = aviso(e, 1, "cancelled", CAFE=2)
    assert r["accion"] == "ignorado" and stock(e, "CAFE") == 10


def test_reembolso_repetido_devuelve_una_sola_vez():
    e = tienda()
    aviso(e, 1, "processing", CAFE=2)
    aviso(e, 1, "refunded", CAFE=2)
    aviso(e, 1, "refunded", CAFE=2)
    assert stock(e, "CAFE") == 10


def test_reactivar_un_pedido_cancelado_vuelve_a_descontar():
    e = tienda()
    aviso(e, 1, "processing", CAFE=2)
    aviso(e, 1, "cancelled", CAFE=2)
    aviso(e, 1, "processing", CAFE=2)
    assert stock(e, "CAFE") == 8


@pytest.mark.parametrize("status", ["pending", "on-hold", "draft", ""])
def test_estados_que_no_mueven_stock(status):
    e = tienda()
    assert aviso(e, 1, status, CAFE=2)["accion"] == "ignorado"
    assert stock(e, "CAFE") == 10


def test_prueba_de_woocommerce_se_responde_sin_error():
    r = procesar_evento("webhook_id=7", True, tienda(), "")
    assert (r["accion"], r["http"]) == ("ignorado", 200)


# ── alertas ────────────────────────────────────────────────────────────────

def test_alerta_al_cruzar_el_minimo():
    e = tienda()
    r = aviso(e, 1, "processing", CAFE=8)
    assert [a["tipo"] for a in r["alertas"]] == ["stock_bajo"]


def test_no_repite_la_alerta_si_ya_estaba_bajo_el_minimo():
    e = tienda(CAFE=2)
    assert aviso(e, 1, "processing", CAFE=1)["alertas"] == []


def test_agotado_y_sobreventa():
    e = tienda()
    assert [a["tipo"] for a in aviso(e, 1, "processing", TAZA=2)["alertas"]] == ["agotado"]
    r = aviso(e, 2, "processing", TAZA=1)
    assert [a["tipo"] for a in r["alertas"]] == ["sobreventa"]
    assert stock(e, "TAZA") == -1


def test_sku_desconocido_avisa_y_sigue_con_el_resto():
    e = tienda()
    r = aviso(e, 1, "processing", CAFE=1, NOEXISTE=4)
    assert stock(e, "CAFE") == 9
    assert [a["tipo"] for a in r["alertas"]] == ["sku_desconocido"]


def test_devolver_no_genera_alertas():
    e = tienda()
    aviso(e, 1, "processing", TAZA=2)
    assert aviso(e, 1, "cancelled", TAZA=2)["alertas"] == []


# ── datos de la hoja ───────────────────────────────────────────────────────

@pytest.mark.parametrize("valor,esperado", [
    (3, 3), ("3", 3), (" 3 ", 3), (3.0, 3), ("-2", -2),
    (2.5, 0), ("2.5", 0), ("", 0), (None, 0), (True, 0),
])
def test_entero(valor, esperado):
    assert entero(valor) == esperado


def test_inventario_desde_la_hoja_con_texto():
    inv = inventario_desde_filas([{"sku": "CAFE", "nombre": "Café", "stock": "12",
                                   "minimo": "3", "product_id": "7"}, {"sku": ""}])
    assert inv == {"CAFE": {"sku": "CAFE", "nombre": "Café", "stock": 12,
                            "minimo": 3, "product_id": 7}}
