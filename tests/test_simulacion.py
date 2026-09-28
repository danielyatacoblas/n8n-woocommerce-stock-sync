"""El día de avisos generado debe dar exactamente las decisiones esperadas."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from simular_dia import simular  # noqa: E402


def test_cada_aviso_toma_la_decision_esperada():
    resultados, _, _ = simular()
    fallos = [(r["descripcion"], r["accion"], r["esperado"])
              for r in resultados if r["accion"] != r["esperado"]]
    assert not fallos


def test_el_stock_final_cuadra_con_el_kardex():
    """Stock final = inicial + suma de movimientos. Si no, algo se perdió o duplicó."""
    resultados, inicial, estado = simular()
    for sku, p in estado["inventario"].items():
        movido = sum(m["cantidad"] for r in resultados for m in r["movimientos"] if m["sku"] == sku)
        assert p["stock"] == inicial[sku]["stock"] + movido, sku


def test_ningun_aviso_rechazado_movio_stock():
    resultados, _, _ = simular()
    assert all(not r["movimientos"] for r in resultados if r["accion"] == "rechazado")
