// Nodo Code de n8n: "Aplicar pedido al stock"
// Espejo en JavaScript de src/sync_tienda.py (misma lógica, misma salida).
// La paridad entre ambos la verifica tests/test_paridad_js.py.
//
// scripts/build_workflow.py reemplaza los marcadores:
//   REGISTRO  'memoria' (demo, stock en la memoria del workflow)
//             'sheets'  (producción, stock y pedidos en Google Sheets)
//   SECRETO   la clave con la que WooCommerce firma los avisos
//   INVENTARIO_INICIAL  data/inventario.json (solo lo usa la demo)

const REGISTRO = '__REGISTRO__';
const SECRETO = __SECRETO__;
const INVENTARIO_INICIAL = __INVENTARIO__;

const DESCUENTAN = ['processing', 'completed'];
const DEVUELVEN = ['cancelled', 'refunded', 'failed'];

// ── utilidades ──

function entero(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? v : 0;
  if (typeof v === 'string' && /^-?\d+$/.test(v.trim())) return parseInt(v.trim(), 10);
  return 0;
}

function inventarioDesdeFilas(filas) {
  const inventario = {};
  for (const f of filas) {
    const sku = String(f.sku || '').trim();
    if (sku) {
      inventario[sku] = {
        sku, nombre: String(f.nombre || sku),
        stock: entero(f.stock), minimo: entero(f.minimo),
        product_id: entero(f.product_id),
      };
    }
  }
  return inventario;
}

function alerta(tipo, producto, pedido) {
  const { nombre: n, sku: s, stock } = producto;
  const mensajes = {
    sobreventa: `Sobreventa: ${n} (${s}) quedó en ${stock}. El pedido #${pedido} ` +
      'vendió más de lo que había: revisar si se puede atender.',
    agotado: `Agotado: ${n} (${s}) con el pedido #${pedido}.`,
    stock_bajo: `Stock bajo: ${n} (${s}) quedan ${stock} (mínimo ${producto.minimo}).`,
  };
  return { tipo, sku: s, stock, mensaje: mensajes[tipo] };
}

// ── decisión ──

function procesarEvento(cuerpo, firmaOk, estado, fecha) {
  estado.pedidos = estado.pedidos || {};
  const pedidos = estado.pedidos;
  const inventario = estado.inventario;
  const r = {
    accion: 'ignorado', http: 200, pedido_id: '', estado_pedido: '',
    motivo: '', movimientos: [], alertas: [], actualizar_tienda: [], fecha,
  };

  if (!firmaOk) return Object.assign(r, { accion: 'rechazado', http: 401, motivo: 'firma inválida' });

  let pedido = null;
  try { pedido = JSON.parse(cuerpo); } catch (e) { pedido = null; }
  if (!pedido || typeof pedido !== 'object' || Array.isArray(pedido) || !pedido.id) {
    // WooCommerce manda un aviso de prueba ("webhook_id=12") al crear el webhook
    r.motivo = 'aviso sin pedido (prueba de WooCommerce)';
    return r;
  }

  const pid = String(pedido.id);
  const status = String(pedido.status || '');
  const previo = pedidos[pid];
  Object.assign(r, { pedido_id: pid, estado_pedido: status, fecha: String(pedido.date_modified || fecha) });

  let signo, accion;
  if (DESCUENTAN.includes(status)) {
    if (previo === 'descontado') { r.motivo = 'el pedido ya descontó stock'; return r; }
    [signo, accion] = [-1, 'descontar'];
  } else if (DEVUELVEN.includes(status)) {
    if (previo !== 'descontado') { r.motivo = 'el pedido no había descontado stock'; return r; }
    [signo, accion] = [1, 'devolver'];
  } else {
    r.motivo = `el estado «${status}» no mueve stock`;
    return r;
  }

  r.accion = accion;
  const tocados = [];
  for (const linea of pedido.line_items || []) {
    const sku = String(linea.sku || '').trim();
    const cantidad = entero(linea.quantity);
    if (cantidad <= 0) continue;
    if (!(sku in inventario)) {
      r.alertas.push({
        tipo: 'sku_desconocido', sku, stock: 0,
        mensaje: `El pedido #${pid} trae ` +
          (sku ? `el SKU «${sku}», que no está` : 'un producto sin SKU, que no está') +
          ` en el inventario: «${linea.name || ''}» x${cantidad}.`,
      });
      continue;
    }
    const p = inventario[sku];
    const antes = p.stock;
    p.stock = antes + signo * cantidad;
    r.movimientos.push({
      sku, nombre: p.nombre, cantidad: signo * cantidad,
      stock_antes: antes, stock_despues: p.stock,
    });
    if (!tocados.includes(sku)) tocados.push(sku);
    if (signo < 0) {
      if (p.stock < 0) r.alertas.push(alerta('sobreventa', p, pid));
      else if (p.stock === 0) r.alertas.push(alerta('agotado', p, pid));
      else if (antes >= p.minimo && p.minimo > p.stock) r.alertas.push(alerta('stock_bajo', p, pid));
    }
  }

  pedidos[pid] = accion === 'descontar' ? 'descontado' : 'devuelto';
  r.actualizar_tienda = tocados.map((s) => ({
    sku: s, product_id: inventario[s].product_id, stock: inventario[s].stock,
  }));
  return r;
}

// ── Ejecución en n8n ──
// (todo lo de arriba se reutiliza tal cual en demo/motor.js)

const crypto = require('crypto');

function firmaValida(cuerpo, recibida) {
  if (!SECRETO || !recibida) return false;
  const esperada = Buffer.from(crypto.createHmac('sha256', SECRETO).update(cuerpo, 'utf8').digest('base64'));
  const dada = Buffer.from(String(recibida));
  // timingSafeEqual tarda lo mismo acierte o no: no da pistas a un atacante
  return esperada.length === dada.length && crypto.timingSafeEqual(esperada, dada);
}

function leerEstado() {
  if (REGISTRO === 'sheets') {
    const pedidos = {};
    for (const i of $('Sheets · Leer pedidos').all()) {
      if (i.json.pedido_id) pedidos[String(i.json.pedido_id)] = String(i.json.estado_stock);
    }
    return {
      inventario: inventarioDesdeFilas($('Sheets · Leer inventario').all().map((i) => i.json)),
      pedidos,
    };
  }
  const memoria = $getWorkflowStaticData('global');
  if (!memoria.inventario) memoria.inventario = inventarioDesdeFilas(INVENTARIO_INICIAL.productos);
  return memoria;
}

const estado = leerEstado();
const webhooks = $('Webhook · Pedido de WooCommerce').all();
// El cuerpo exacto hace falta para la firma: si se volviera a serializar el
// JSON, un espacio distinto cambiaría la firma. El nodo "Leer cuerpo exacto"
// lo deja como texto; se lee por nombre porque en producción $input trae las
// filas de la hoja, no el aviso.
const cuerpos = $('Leer cuerpo exacto').all();

return cuerpos.map((item, i) => {
  const cuerpo = String(item.json.cuerpo || '');
  const cabeceras = (webhooks[i] && webhooks[i].json.headers) || {};
  const firmaOk = firmaValida(cuerpo, cabeceras['x-wc-webhook-signature']);
  return { json: procesarEvento(cuerpo, firmaOk, estado, $now.toISO()) };
});
