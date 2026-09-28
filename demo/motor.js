// Generado por scripts/build_workflow.py. No editar a mano.
// Misma lógica que el nodo Code de n8n, para la demo en modo simulado.
// Nodo Code de n8n: "Aplicar pedido al stock"
// Espejo en JavaScript de src/sync_tienda.py (misma lógica, misma salida).
// La paridad entre ambos la verifica tests/test_paridad_js.py.
//
// scripts/build_workflow.py reemplaza los marcadores:
//   REGISTRO  'memoria' (demo, stock en la memoria del workflow)
//             'sheets'  (producción, stock y pedidos en Google Sheets)
//   SECRETO   la clave con la que WooCommerce firma los avisos
//   INVENTARIO_INICIAL  data/inventario.json (solo lo usa la demo)

const REGISTRO = 'memoria';
const SECRETO = "clave-demo-no-usar-en-produccion";
const INVENTARIO_INICIAL = {
  "tienda": "Tostaduría Selva Alta",
  "nota": "Tienda ficticia. Productos, precios y stock inventados para la demostración.",
  "productos": [
    {
      "sku": "CAF-VRS-250",
      "product_id": 101,
      "nombre": "Café Villa Rica tostado 250 g",
      "stock": 40,
      "minimo": 10
    },
    {
      "sku": "CAF-VRS-1K",
      "product_id": 102,
      "nombre": "Café Villa Rica tostado 1 kg",
      "stock": 12,
      "minimo": 4
    },
    {
      "sku": "CAF-CHA-250",
      "product_id": 103,
      "nombre": "Café Chanchamayo orgánico 250 g",
      "stock": 25,
      "minimo": 8
    },
    {
      "sku": "CAF-CUS-250",
      "product_id": 104,
      "nombre": "Café Cusco geisha 250 g",
      "stock": 6,
      "minimo": 3
    },
    {
      "sku": "CAF-DES-250",
      "product_id": 105,
      "nombre": "Café descafeinado 250 g",
      "stock": 9,
      "minimo": 3
    },
    {
      "sku": "PRE-V60",
      "product_id": 201,
      "nombre": "Gotero V60 de cerámica",
      "stock": 5,
      "minimo": 2
    },
    {
      "sku": "PRE-PRENSA",
      "product_id": 202,
      "nombre": "Prensa francesa 600 ml",
      "stock": 8,
      "minimo": 2
    },
    {
      "sku": "ACC-FILTROS",
      "product_id": 301,
      "nombre": "Filtros de papel x100",
      "stock": 30,
      "minimo": 10
    },
    {
      "sku": "ACC-TAZA",
      "product_id": 302,
      "nombre": "Taza de cerámica artesanal",
      "stock": 3,
      "minimo": 2
    },
    {
      "sku": "KIT-REGALO",
      "product_id": 401,
      "nombre": "Kit regalo café + taza",
      "stock": 4,
      "minimo": 2
    }
  ]
};

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

window.MotorTienda = { INVENTARIO_INICIAL, inventarioDesdeFilas, procesarEvento };
