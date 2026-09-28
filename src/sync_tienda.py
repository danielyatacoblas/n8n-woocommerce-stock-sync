"""Sincronización de stock a partir de los webhooks de pedidos de WooCommerce.

Es la misma lógica que corre en el nodo Code de n8n
(workflows/src/sincronizar_pedido.js); tests/test_paridad_js.py verifica que
ambas copias den el mismo resultado.

Tres problemas que resuelve y que un flujo ingenuo no ve:
  1. WooCommerce reintenta un webhook si no recibe respuesta a tiempo, y
     manda 'order.updated' cada vez que alguien toca el pedido. Descontar en
     cada aviso vaciaría el inventario: el stock se mueve UNA vez por pedido.
  2. Cualquiera que conozca la URL del webhook podría inventar pedidos. Cada
     aviso trae una firma HMAC-SHA256 que se verifica antes de tocar el stock.
  3. Un pedido cancelado devuelve el stock solo si antes lo había descontado.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

DESCUENTAN = ("processing", "completed")          # pagado o entregado
DEVUELVEN = ("cancelled", "refunded", "failed")


# ── firma ──────────────────────────────────────────────────────────────────

def firmar(cuerpo: str, secreto: str) -> str:
    """Firma que WooCommerce pone en la cabecera X-WC-Webhook-Signature."""
    digest = hmac.new(secreto.encode(), cuerpo.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def firma_valida(cuerpo: str, recibida: str, secreto: str) -> bool:
    if not secreto or not recibida:
        return False
    # compare_digest tarda lo mismo acierte o no: no da pistas a un atacante
    return hmac.compare_digest(firmar(cuerpo, secreto), recibida)


# ── utilidades ─────────────────────────────────────────────────────────────

def entero(v) -> int:
    """Cantidades y stock: solo enteros. '3', 3 y 3.0 valen 3; lo demás, 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else 0
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return 0


def inventario_desde_filas(filas: list[dict]) -> dict:
    """Arma el inventario desde la hoja (o el JSON), donde todo puede venir como texto."""
    inventario = {}
    for f in filas:
        sku = str(f.get("sku") or "").strip()
        if sku:
            inventario[sku] = {"sku": sku, "nombre": str(f.get("nombre") or sku),
                               "stock": entero(f.get("stock")),
                               "minimo": entero(f.get("minimo")),
                               "product_id": entero(f.get("product_id"))}
    return inventario


def alerta(tipo: str, producto: dict, pedido: str) -> dict:
    n, s, stock = producto["nombre"], producto["sku"], producto["stock"]
    mensajes = {
        "sobreventa": f"Sobreventa: {n} ({s}) quedó en {stock}. El pedido #{pedido} "
                      "vendió más de lo que había: revisar si se puede atender.",
        "agotado": f"Agotado: {n} ({s}) con el pedido #{pedido}.",
        "stock_bajo": f"Stock bajo: {n} ({s}) quedan {stock} (mínimo {producto['minimo']}).",
    }
    return {"tipo": tipo, "sku": s, "stock": stock, "mensaje": mensajes[tipo]}


# ── decisión ───────────────────────────────────────────────────────────────

def procesar_evento(cuerpo: str, firma_ok: bool, estado: dict, fecha: str) -> dict:
    """Aplica un aviso de WooCommerce al inventario.

    estado = {"inventario": {sku: producto}, "pedidos": {id: "descontado"|"devuelto"}}
    """
    pedidos = estado.setdefault("pedidos", {})
    inventario = estado["inventario"]
    r = {"accion": "ignorado", "http": 200, "pedido_id": "", "estado_pedido": "",
         "motivo": "", "movimientos": [], "alertas": [], "actualizar_tienda": [],
         "fecha": fecha}

    if not firma_ok:
        r.update(accion="rechazado", http=401, motivo="firma inválida")
        return r

    try:
        pedido = json.loads(cuerpo)
    except ValueError:
        pedido = None
    if not isinstance(pedido, dict) or not pedido.get("id"):
        # WooCommerce manda un aviso de prueba ("webhook_id=12") al crear el webhook
        r["motivo"] = "aviso sin pedido (prueba de WooCommerce)"
        return r

    pid = str(pedido["id"])
    status = str(pedido.get("status") or "")
    previo = pedidos.get(pid)
    r.update(pedido_id=pid, estado_pedido=status, fecha=str(pedido.get("date_modified") or fecha))

    if status in DESCUENTAN:
        if previo == "descontado":
            r["motivo"] = "el pedido ya descontó stock"
            return r
        signo, accion = -1, "descontar"
    elif status in DEVUELVEN:
        if previo != "descontado":
            r["motivo"] = "el pedido no había descontado stock"
            return r
        signo, accion = 1, "devolver"
    else:
        r["motivo"] = f"el estado «{status}» no mueve stock"
        return r

    r["accion"] = accion
    tocados = []
    for linea in pedido.get("line_items") or []:
        sku = str(linea.get("sku") or "").strip()
        cantidad = entero(linea.get("quantity"))
        if cantidad <= 0:
            continue
        if sku not in inventario:
            r["alertas"].append({
                "tipo": "sku_desconocido", "sku": sku, "stock": 0,
                "mensaje": f"El pedido #{pid} trae "
                           + (f"el SKU «{sku}», que no está" if sku else "un producto sin SKU, que no está")
                           + f" en el inventario: «{linea.get('name') or ''}» x{cantidad}."})
            continue
        p = inventario[sku]
        antes = p["stock"]
        p["stock"] = antes + signo * cantidad
        r["movimientos"].append({"sku": sku, "nombre": p["nombre"],
                                 "cantidad": signo * cantidad,
                                 "stock_antes": antes, "stock_despues": p["stock"]})
        if sku not in tocados:
            tocados.append(sku)
        if signo < 0:
            if p["stock"] < 0:
                r["alertas"].append(alerta("sobreventa", p, pid))
            elif p["stock"] == 0:
                r["alertas"].append(alerta("agotado", p, pid))
            elif antes >= p["minimo"] > p["stock"]:
                r["alertas"].append(alerta("stock_bajo", p, pid))

    pedidos[pid] = "descontado" if accion == "descontar" else "devuelto"
    r["actualizar_tienda"] = [{"sku": s, "product_id": inventario[s]["product_id"],
                               "stock": inventario[s]["stock"]} for s in tocados]
    return r
