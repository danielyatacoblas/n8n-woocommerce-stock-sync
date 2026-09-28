// Ejecuta el código del nodo Code de n8n fuera de n8n, simulando sus globals.
// Uso:  node tests/correr_nodo_js.mjs <avisos.json>
// La entrada es una lista de avisos {cuerpo, firma}. El stock parte de
// data/inventario.json y persiste entre avisos, como en la memoria del workflow.
// Salida: JSON por stdout con el resultado de cada aviso.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);

const jsCode = readFileSync(join(ROOT, 'workflows', 'src', 'sincronizar_pedido.js'), 'utf8')
  .replace("'__REGISTRO__'", "'memoria'")
  .replace('__SECRETO__', JSON.stringify('clave-demo-no-usar-en-produccion'))
  .replace('__INVENTARIO__', readFileSync(join(ROOT, 'data', 'inventario.json'), 'utf8'));

const avisos = JSON.parse(readFileSync(process.argv[2], 'utf8'));

const staticData = {};
const nodos = {
  'Webhook · Pedido de WooCommerce': avisos.map((a) => ({
    json: { headers: a.firma === null ? {} : { 'x-wc-webhook-signature': a.firma } },
  })),
  'Leer cuerpo exacto': avisos.map((a) => ({ json: { cuerpo: a.cuerpo } })),
};
const $ = (nombre) => ({ all: () => nodos[nombre] });
const $now = { toISO: () => '2026-09-10T00:00:00' };

const ejecutarNodo = new Function('$', '$getWorkflowStaticData', '$now', 'require', jsCode);
const salida = ejecutarNodo($, () => staticData, $now, require);

process.stdout.write(JSON.stringify(salida.map((s) => s.json)));
