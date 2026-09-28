"""Revisa los workflows generados: que se puedan importar y no filtren secretos."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = {p.name: json.loads(p.read_text(encoding="utf-8"))
             for p in (ROOT / "workflows").glob("*.json")}


def _conexiones(wf):
    for origen, salidas in wf["connections"].items():
        for ramas in salidas.values():
            for i, rama in enumerate(ramas):
                for destino in rama:
                    yield origen, i, destino["node"]


def _nodo(wf, nombre):
    return next(n for n in wf["nodes"] if n["name"] == nombre)


def test_existen_los_dos_workflows():
    assert set(WORKFLOWS) == {"tienda_demo.json", "tienda_produccion.json"}


@pytest.mark.parametrize("nombre", sorted(WORKFLOWS))
def test_conexiones_validas_y_sin_nodos_sueltos(nombre):
    wf = WORKFLOWS[nombre]
    nodos = {n["name"] for n in wf["nodes"]}
    assert len(nodos) == len(wf["nodes"])
    tocados = set()
    for origen, _, destino in _conexiones(wf):
        assert origen in nodos and destino in nodos, f"{origen} → {destino}"
        tocados.update((origen, destino))
    assert tocados == nodos


@pytest.mark.parametrize("nombre", sorted(WORKFLOWS))
def test_no_hay_credenciales(nombre):
    texto = json.dumps(WORKFLOWS[nombre])
    assert "credentials" not in texto
    assert not re.search(r"(ck|cs)_[a-f0-9]{40}", texto), "clave de la API de WooCommerce"


def test_produccion_no_lleva_la_clave_de_la_demo():
    js = _nodo(WORKFLOWS["tienda_produccion.json"], "Aplicar pedido al stock")["parameters"]["jsCode"]
    assert "clave-demo" not in js
    assert "const SECRETO = $env.WC_WEBHOOK_SECRET;" in js


def test_la_firma_se_verifica_sobre_el_cuerpo_exacto():
    for wf in WORKFLOWS.values():
        webhook = _nodo(wf, "Webhook · Pedido de WooCommerce")
        assert webhook["parameters"]["options"]["rawBody"] is True
        destinos = {d for o, _, d in _conexiones(wf) if o == "Webhook · Pedido de WooCommerce"}
        assert destinos == {"Leer cuerpo exacto"}


def test_se_responde_a_woocommerce_con_el_codigo_de_la_decision():
    resp = _nodo(WORKFLOWS["tienda_produccion.json"], "Responder a WooCommerce")
    assert resp["parameters"]["options"]["responseCode"] == "={{ $json.http }}"


def test_si_la_tienda_no_responde_se_reintenta_y_se_avisa():
    wf = WORKFLOWS["tienda_produccion.json"]
    http = _nodo(wf, "WooCommerce · Actualizar stock")
    assert http["retryOnFail"] and http["maxTries"] == 3
    assert http["onError"] == "continueErrorOutput"
    assert ("WooCommerce · Actualizar stock", 1, "Telegram · Falló la tienda") in set(_conexiones(wf))


def test_la_hoja_de_pedidos_es_la_memoria_de_idempotencia():
    wf = WORKFLOWS["tienda_produccion.json"]
    guardar = _nodo(wf, "Sheets · Guardar estado del pedido")["parameters"]
    assert guardar["operation"] == "appendOrUpdate"
    assert guardar["columns"]["matchingColumns"] == ["pedido_id"]
