#!/usr/bin/env python3
"""Construye los workflows de n8n y el motor de la tienda de demostración.

    python scripts/build_workflow.py

Genera:
  workflows/tienda_demo.json        stock en la memoria del workflow, SIN credenciales
  workflows/tienda_produccion.json  WooCommerce + Google Sheets + Telegram
  demo/motor.js                     la misma lógica, para la demo en modo simulado
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "workflows" / "src" / "sincronizar_pedido.js"
INVENTARIO = ROOT / "data" / "inventario.json"
OUT = ROOT / "workflows"
MOTOR = ROOT / "demo" / "motor.js"

SECRETO_DEMO = "clave-demo-no-usar-en-produccion"
MARCA_EJECUCION = "// ── Ejecución en n8n ──"
ID_HOJA = {"__rl": True, "value": "REEMPLAZAR_ID_HOJA", "mode": "id"}


def codigo(registro: str, secreto_js: str) -> str:
    js = JS.read_text(encoding="utf-8")
    inventario = json.loads(INVENTARIO.read_text(encoding="utf-8"))
    reemplazos = {"'__REGISTRO__'": f"'{registro}'", "__SECRETO__": secreto_js,
                  "__INVENTARIO__": json.dumps(inventario, ensure_ascii=False, indent=2)}
    for marca, valor in reemplazos.items():
        if js.count(marca) != 1:
            raise SystemExit(f"se esperaba una sola vez {marca} en {JS}")
        js = js.replace(marca, valor)
    return js


def motor_navegador() -> str:
    js = codigo("memoria", json.dumps(SECRETO_DEMO))
    logica = js.split(MARCA_EJECUCION)[0]
    return ("// Generado por scripts/build_workflow.py. No editar a mano.\n"
            "// Misma lógica que el nodo Code de n8n, para la demo en modo simulado.\n"
            + logica +
            "window.MotorTienda = { INVENTARIO_INICIAL, inventarioDesdeFilas, procesarEvento };\n")


def _node(nid, name, ntype, tv, pos, params, extra=None):
    n = {"parameters": params, "id": nid, "name": name, "type": ntype,
         "typeVersion": tv, "position": pos}
    if extra:
        n.update(extra)
    return n


def _link(*destinos):
    return [{"node": d, "type": "main", "index": 0} for d in destinos]


def _webhook(nid, nombre, metodo, ruta, pos, raw=False):
    opciones = {"allowedOrigins": "*"}
    if raw:
        opciones["rawBody"] = True
    return _node(nid, nombre, "n8n-nodes-base.webhook", 2, pos,
                 {"httpMethod": metodo, "path": ruta, "responseMode": "responseNode",
                  "options": opciones}, {"webhookId": ruta.replace("/", "-")})


def _cuerpo_exacto(pos):
    return _node("raw-1", "Leer cuerpo exacto", "n8n-nodes-base.extractFromFile", 1, pos,
                 {"operation": "text", "binaryPropertyName": "data",
                  "destinationKey": "cuerpo", "options": {}},
                 {"notes": "Guarda el cuerpo tal como llegó: la firma se calcula sobre esos bytes."})


def _responder(nid, nombre, pos, codigo_http="={{ $json.http }}"):
    return _node(nid, nombre, "n8n-nodes-base.respondToWebhook", 1.1, pos,
                 {"respondWith": "firstIncomingItem",
                  "options": {"responseCode": codigo_http}})


def build_demo() -> dict:
    ver = ("const m = $getWorkflowStaticData('global');\n"
           "const inicial = " + json.dumps(json.loads(INVENTARIO.read_text(encoding="utf-8")),
                                           ensure_ascii=False) + ";\n"
           "const productos = m.inventario ? Object.values(m.inventario) : inicial.productos;\n"
           "return [{ json: { tienda: inicial.tienda, productos, pedidos: m.pedidos || {} } }];\n")
    reiniciar = ("const m = $getWorkflowStaticData('global');\n"
                 "delete m.inventario;\ndelete m.pedidos;\n"
                 "return [{ json: { reiniciado: true } }];\n")
    nodes = [
        _webhook("wh-1", "Webhook · Pedido de WooCommerce", "POST", "tienda-demo", [0, 0], raw=True),
        _cuerpo_exacto([220, 0]),
        _node("code-1", "Aplicar pedido al stock", "n8n-nodes-base.code", 2, [440, 0],
              {"jsCode": codigo("memoria", json.dumps(SECRETO_DEMO))},
              {"notes": "Clave de firma de DEMO, pública a propósito. En producción "
                        "se lee de la variable de entorno WC_WEBHOOK_SECRET."}),
        _responder("resp-1", "Responder", [660, 0]),
        _webhook("wh-2", "Webhook · Ver inventario", "GET", "tienda-demo/inventario", [0, 220]),
        _node("code-2", "Leer inventario", "n8n-nodes-base.code", 2, [220, 220], {"jsCode": ver}),
        _responder("resp-2", "Responder inventario", [440, 220], 200),
        _webhook("wh-3", "Webhook · Reiniciar demo", "POST", "tienda-demo/reiniciar", [0, 400]),
        _node("code-3", "Volver al stock inicial", "n8n-nodes-base.code", 2, [220, 400],
              {"jsCode": reiniciar}),
        _responder("resp-3", "Responder reinicio", [440, 400], 200),
    ]
    connections = {
        "Webhook · Pedido de WooCommerce": {"main": [_link("Leer cuerpo exacto")]},
        "Leer cuerpo exacto": {"main": [_link("Aplicar pedido al stock")]},
        "Aplicar pedido al stock": {"main": [_link("Responder")]},
        "Webhook · Ver inventario": {"main": [_link("Leer inventario")]},
        "Leer inventario": {"main": [_link("Responder inventario")]},
        "Webhook · Reiniciar demo": {"main": [_link("Volver al stock inicial")]},
        "Volver al stock inicial": {"main": [_link("Responder reinicio")]},
    }
    return {"id": "tiendademo", "name": "Sincronización de tienda · DEMO sin credenciales",
            "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1"}, "pinData": {},
            "meta": {"instanceId": "tienda-demo"}, "tags": []}


def _leer_hoja(nid, nombre, pestana, pos):
    return _node(nid, nombre, "n8n-nodes-base.googleSheets", 4.5, pos,
                 {"documentId": ID_HOJA,
                  "sheetName": {"__rl": True, "value": pestana, "mode": "name"},
                  "options": {}},
                 {"executeOnce": True, "alwaysOutputData": True})


def _separar(nid, nombre, campo, pos):
    return _node(nid, nombre, "n8n-nodes-base.splitOut", 1, pos,
                 {"fieldToSplitOut": campo, "include": "selectedOtherFields",
                  "fieldsToInclude": "pedido_id, accion, fecha", "options": {}})


def _telegram(nid, nombre, texto, pos):
    return _node(nid, nombre, "n8n-nodes-base.telegram", 1.2, pos,
                 {"chatId": "REEMPLAZAR_CHAT_EQUIPO", "text": texto,
                  "additionalFields": {"appendAttribution": False}})


def build_prod() -> dict:
    nodes = [
        _webhook("wh-1", "Webhook · Pedido de WooCommerce", "POST", "woocommerce-pedidos",
                 [0, 300], raw=True),
        _cuerpo_exacto([220, 300]),
        _leer_hoja("gs-inv", "Sheets · Leer inventario", "Inventario", [440, 300]),
        _leer_hoja("gs-ped", "Sheets · Leer pedidos", "Pedidos", [660, 300]),
        _node("code-1", "Aplicar pedido al stock", "n8n-nodes-base.code", 2, [880, 300],
              {"jsCode": codigo("sheets", "$env.WC_WEBHOOK_SECRET")},
              {"notes": "Necesita en el servidor de n8n: WC_WEBHOOK_SECRET, "
                        "NODE_FUNCTION_ALLOW_BUILTIN=crypto y "
                        "N8N_BLOCK_ENV_ACCESS_IN_NODE=false (ver GUIA.md)."}),
        _node("resp-1", "Responder a WooCommerce", "n8n-nodes-base.respondToWebhook", 1.1,
              [1100, 100],
              {"respondWith": "json",
               "responseBody": "={{ { accion: $json.accion, motivo: $json.motivo } }}",
               "options": {"responseCode": "={{ $json.http }}"}},
              {"notes": "Se responde enseguida: WooCommerce desactiva el webhook "
                        "tras varios avisos sin respuesta."}),
        _node("if-1", "¿Movió stock?", "n8n-nodes-base.if", 2.2, [1100, 300],
              {"conditions": {
                  "options": {"caseSensitive": True, "leftValue": "",
                              "typeValidation": "strict", "version": 2},
                  "conditions": [
                      {"id": "m1", "leftValue": "={{ $json.accion }}", "rightValue": "descontar",
                       "operator": {"type": "string", "operation": "equals"}},
                      {"id": "m2", "leftValue": "={{ $json.accion }}", "rightValue": "devolver",
                       "operator": {"type": "string", "operation": "equals"}}],
                  "combinator": "or"},
               "options": {}}),
        _node("gs-ped-w", "Sheets · Guardar estado del pedido", "n8n-nodes-base.googleSheets", 4.5,
              [1340, 60],
              {"operation": "appendOrUpdate", "documentId": ID_HOJA,
               "sheetName": {"__rl": True, "value": "Pedidos", "mode": "name"},
               "columns": {"mappingMode": "defineBelow",
                           "value": {"pedido_id": "={{ $json.pedido_id }}",
                                     "estado_stock": "={{ $json.accion === 'descontar' ? 'descontado' : 'devuelto' }}",
                                     "actualizado": "={{ $json.fecha }}"},
                           "matchingColumns": ["pedido_id"], "schema": []},
               "options": {}},
              {"notes": "Es la memoria de idempotencia: un pedido ya descontado no vuelve a descontar."}),
        _separar("sp-mov", "Separar movimientos", "movimientos", [1340, 220]),
        _node("gs-kardex", "Sheets · Kardex", "n8n-nodes-base.googleSheets", 4.5, [1560, 220],
              {"operation": "append", "documentId": ID_HOJA,
               "sheetName": {"__rl": True, "value": "Kardex", "mode": "name"},
               "columns": {"mappingMode": "autoMapInputData", "value": {}},
               "options": {}}),
        _separar("sp-act", "Separar productos a actualizar", "actualizar_tienda", [1340, 400]),
        _node("gs-inv-w", "Sheets · Actualizar inventario", "n8n-nodes-base.googleSheets", 4.5,
              [1560, 380],
              {"operation": "update", "documentId": ID_HOJA,
               "sheetName": {"__rl": True, "value": "Inventario", "mode": "name"},
               "columns": {"mappingMode": "defineBelow",
                           "value": {"sku": "={{ $json.sku }}", "stock": "={{ $json.stock }}"},
                           "matchingColumns": ["sku"], "schema": []},
               "options": {}}),
        _node("http-wc", "WooCommerce · Actualizar stock", "n8n-nodes-base.httpRequest", 4.2,
              [1560, 540],
              {"method": "PUT",
               "url": "=REEMPLAZAR_URL_TIENDA/wp-json/wc/v3/products/{{ $json.product_id }}",
               "authentication": "genericCredentialType", "genericAuthType": "httpBasicAuth",
               "sendBody": True, "specifyBody": "json",
               "jsonBody": "={{ { manage_stock: true, stock_quantity: $json.stock } }}",
               "options": {"timeout": 15000}},
              {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 3000,
               "onError": "continueErrorOutput",
               "notes": "La hoja es la fuente de verdad (también descuenta ventas de la "
                        "tienda física); aquí se copia el stock a la tienda online."}),
        _telegram("tg-wc", "Telegram · Falló la tienda",
                  "=No se pudo actualizar el stock de {{ $('Separar productos a actualizar').item.json.sku }} "
                  "en la tienda online tras 3 intentos. Stock correcto: "
                  "{{ $('Separar productos a actualizar').item.json.stock }}.",
                  [1780, 620]),
        _separar("sp-al", "Separar alertas", "alertas", [1100, 520]),
        _telegram("tg-al", "Telegram · Alerta de stock", "={{ $json.mensaje }}", [1340, 580]),
    ]
    connections = {
        "Webhook · Pedido de WooCommerce": {"main": [_link("Leer cuerpo exacto")]},
        "Leer cuerpo exacto": {"main": [_link("Sheets · Leer inventario")]},
        "Sheets · Leer inventario": {"main": [_link("Sheets · Leer pedidos")]},
        "Sheets · Leer pedidos": {"main": [_link("Aplicar pedido al stock")]},
        "Aplicar pedido al stock": {"main": [_link("Responder a WooCommerce", "¿Movió stock?",
                                                   "Separar alertas")]},
        "¿Movió stock?": {"main": [_link("Sheets · Guardar estado del pedido",
                                         "Separar movimientos",
                                         "Separar productos a actualizar"), []]},
        "Separar movimientos": {"main": [_link("Sheets · Kardex")]},
        "Separar productos a actualizar": {"main": [_link("Sheets · Actualizar inventario",
                                                          "WooCommerce · Actualizar stock")]},
        "WooCommerce · Actualizar stock": {"main": [[], _link("Telegram · Falló la tienda")]},
        "Separar alertas": {"main": [_link("Telegram · Alerta de stock")]},
    }
    return {"id": "tiendaprod", "name": "Sincronización de tienda · producción",
            "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1"}, "pinData": {},
            "meta": {"instanceId": "tienda-prod"}, "tags": []}


def main():
    salidas = {
        OUT / "tienda_demo.json": json.dumps(build_demo(), indent=2, ensure_ascii=False) + "\n",
        OUT / "tienda_produccion.json": json.dumps(build_prod(), indent=2, ensure_ascii=False) + "\n",
        MOTOR: motor_navegador(),
    }
    for ruta, contenido in salidas.items():
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
        print(f"ok  {ruta.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
