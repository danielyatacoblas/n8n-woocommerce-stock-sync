"""Paridad: el nodo Code de n8n (JS) y la lógica Python deben decidir igual.

El nodo JS verifica la firma con el módulo crypto de Node y Python con hmac:
el test también confirma que ambos aceptan y rechazan los mismos avisos.
Requiere Node.js; si no está instalado, se salta.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync_tienda import (firma_valida, firmar,  # noqa: E402
                             inventario_desde_filas, procesar_evento)

SECRETO = "clave-demo-no-usar-en-produccion"
RUNNER = ROOT / "tests" / "correr_nodo_js.mjs"
PRODUCTOS = json.loads((ROOT / "data" / "inventario.json").read_text(encoding="utf-8"))["productos"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="Node.js no está instalado")


def _python(avisos):
    estado = {"inventario": inventario_desde_filas(PRODUCTOS)}
    return [procesar_evento(a["cuerpo"], firma_valida(a["cuerpo"], a["firma"] or "", SECRETO),
                            estado, "2026-09-10T00:00:00") for a in avisos]


def _js(avisos, tmp_path):
    ruta = tmp_path / "avisos.json"
    ruta.write_text(json.dumps(avisos, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(["node", str(RUNNER), str(ruta)],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.fail(f"el nodo JS falló:\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_el_dia_completo_da_lo_mismo(tmp_path):
    eventos = json.loads((ROOT / "data" / "eventos.json").read_text(encoding="utf-8"))
    avisos = [{"cuerpo": e["cuerpo"], "firma": e["firma"]} for e in eventos]
    py, js = _python(avisos), _js(avisos, tmp_path)
    for e, p, j in zip(eventos, py, js):
        assert p == j, f"divergen en «{e['descripcion']}»\n python={p}\n js    ={j}"


def test_casos_raros(tmp_path):
    cuerpos = [
        '{"id": 1, "status": "processing", "line_items": [{"sku": "ACC-TAZA", "quantity": "2"}]}',
        '{"id": 2, "status": "processing", "line_items": [{"sku": "ACC-TAZA", "quantity": 2.0}]}',
        '{"id": 3, "status": "processing", "line_items": [{"sku": "ACC-TAZA", "quantity": 1.5}]}',
        '{"id": 4, "status": "processing", "line_items": [{"sku": " PRE-V60 ", "quantity": -3}]}',
        '{"id": 5, "status": "processing", "line_items": null}',
        '[1, 2, 3]', '"texto"', '', '{"id": 0, "status": "processing"}',
        '{"id": "A-7", "status": "Processing", "line_items": []}',
        '{"id": 6, "status": "processing", "line_items": [{"sku": "ACC-TAZA", "quantity": true}]}',
    ]
    avisos = [{"cuerpo": c, "firma": firmar(c, SECRETO)} for c in cuerpos]
    avisos.append({"cuerpo": cuerpos[0], "firma": None})          # sin cabecera
    avisos.append({"cuerpo": cuerpos[0], "firma": "corta"})       # largo distinto
    assert _python(avisos) == _js(avisos, tmp_path)
