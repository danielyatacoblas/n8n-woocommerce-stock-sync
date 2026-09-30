<h1 align="center">Sincronización de tienda online con n8n</h1>

<p align="center"><i>Cada pedido mueve el stock una sola vez, y nadie se entera de un agotado por un cliente molesto</i></p>

<p align="center">
  <img alt="tests" src="https://img.shields.io/badge/tests-49%20passed-brightgreen">
  <img alt="simulación" src="https://img.shields.io/badge/simulaci%C3%B3n-17%2F17%20avisos-brightgreen">
  <img alt="n8n" src="https://img.shields.io/badge/n8n-self--hosted-EA4B71">
  <img alt="python" src="https://img.shields.io/badge/python-3.12-3776AB">
  <img alt="licencia" src="https://img.shields.io/badge/licencia-MIT-blue">
</p>

---

## Para qué existe este repositorio

Una tienda vende por WooCommerce y también en su local. El stock se lleva en una hoja de cálculo que alguien actualiza a mano al final del día. Mientras tanto, la web sigue vendiendo productos que ya se acabaron, nadie avisa cuando algo baja del mínimo y un pedido cancelado a veces devuelve stock que nunca se había descontado.

**Este flujo recibe cada aviso de pedido de WooCommerce, verifica que sea auténtico, mueve el stock una sola vez por pedido, registra el movimiento, copia el stock correcto a la tienda y avisa al equipo cuando algo se agota o se vende de más.**

```mermaid
flowchart TD
    W["WooCommerce<br/>aviso de pedido"] --> F
    subgraph N ["n8n"]
        F{"¿Firma<br/>válida?"}
        F -->|no| R["401 · no se toca nada"]
        F -->|sí| E{"¿Qué pasó<br/>con el pedido?"}
        E -->|"pagado por<br/>primera vez"| D["Descontar"]
        E -->|"cancelado después<br/>de pagar"| V["Devolver"]
        E -->|"reintento, repetido<br/>o sin pago"| I["Ignorar"]
    end
    D --> K["Kardex e inventario<br/>Google Sheets"]
    V --> K
    K --> T["Stock actualizado<br/>en WooCommerce"]
    D -.->|"agotado, sobreventa,<br/>stock bajo"| A["Alerta por Telegram"]
```

---

## Arquitectura

<p align="center"><img src="docs/arquitectura.png" alt="Arquitectura: entradas, pasos dentro de n8n y salidas" width="900"></p>

---

## El workflow en n8n

<p align="center"><img src="docs/workflow_n8n.png" alt="Workflow de producción abierto en el editor de n8n" width="900"></p>

<p align="center"><i>Captura del editor de n8n 2.40 con <code>workflows/tienda_produccion.json</code> importado.
Los triángulos rojos solo indican credenciales por conectar (Google, Telegram, IA).</i></p>

### Paso a paso: un pedido legítimo, su reintento y un pedido falso

```mermaid
sequenceDiagram
    autonumber
    participant W as WooCommerce
    participant N as Webhook (Raw Body)
    participant C as Code · Aplicar pedido
    participant P as Sheets · Pedidos
    participant I as Sheets · Inventario y Kardex
    W->>N: n.º 1001 processing + firma HMAC
    N->>C: bytes exactos del cuerpo
    C->>C: HMAC-SHA256 con $env.WC_WEBHOOK_SECRET ✓
    C->>P: ¿n.º 1001 ya descontó?
    P-->>C: no
    C->>I: stock -2 y fila en el kardex
    C->>P: n.º 1001 = descontado (appendOrUpdate)
    C-->>W: 200
    W->>N: n.º 1001 otra vez (no recibió respuesta a tiempo)
    N->>C: bytes exactos
    C->>P: ¿n.º 1001 ya descontó?
    P-->>C: sí → ignorar
    C-->>W: 200, el stock no se toca
    Note over W,N: alguien descubre la URL del webhook
    W->>N: pedido inventado, firma falsa
    N->>C: bytes exactos
    C->>C: HMAC no coincide ✗
    C-->>W: 401, no se lee ni se toca nada
```

### Técnicas de n8n que usa

**Sincronización de tienda · producción** · 16 nodos

| Técnica de n8n | Para qué se usa aquí |
| --- | --- |
| Disparo por eventos (webhook o trigger de la app) | reacciona al instante, sin revisar cada tanto |
| Webhook con Raw Body | conserva los bytes exactos para verificar firmas HMAC |
| Extract from File | lee PDFs o archivos de texto dentro del flujo |
| Execute Once | lee una hoja completa una sola vez aunque lleguen varios items |
| Always Output Data | una hoja vacía no corta el flujo |
| Lectura de otros nodos por nombre ($('Nodo')) | usa datos de pasos anteriores aunque $input traiga otra cosa |
| Secretos por variables de entorno ($env) | ninguna clave queda escrita en el workflow |
| Módulo crypto de Node en el nodo Code | calcula firmas HMAC-SHA256 dentro de n8n |
| Respuesta HTTP con código dinámico | responde 200 o 401 según lo que decidió el flujo |
| Upsert en Google Sheets (appendOrUpdate) | actualiza la fila si existe o la crea si no |
| Split Out | convierte una lista en items para procesarlos uno por uno |
| Salida de error del nodo (On Error → error output) | si un servicio falla, el flujo sigue por otra rama |
| Reintentos del nodo (Retry On Fail) | absorbe caídas breves de una API externa |
| HTTP Request con credencial genérica | llama a cualquier API aunque n8n no tenga un nodo para ella |

<details><summary>Nodo por nodo</summary>

| Nodo | Tipo | Configuración |
| --- | --- | --- |
| Webhook · Pedido de WooCommerce | Webhook | `POST /woocommerce-pedidos`, Raw Body |
| Leer cuerpo exacto | Extract from File | operación `text`. Guarda el cuerpo tal como llegó: la firma se calcula sobre esos bytes. |
| Sheets · Leer inventario | Google Sheets | pestaña `Inventario`, Execute Once, Always Output Data |
| Sheets · Leer pedidos | Google Sheets | pestaña `Pedidos`, Execute Once, Always Output Data |
| Aplicar pedido al stock | Code (JavaScript) | 244 líneas generadas desde `workflows/src/`. Necesita en el servidor de n8n: WC_WEBHOOK_SECRET, NODE_FUNCTION_ALLOW_BUILTIN=crypto y N8N_BLOCK_ENV_ACCESS_IN_NODE=false (ver GUIA.md). |
| Responder a WooCommerce | Respond to Webhook | Se responde enseguida: WooCommerce desactiva el webhook tras varios avisos sin respuesta. |
| ¿Movió stock? | If | — |
| Sheets · Guardar estado del pedido | Google Sheets | operación `appendOrUpdate`, pestaña `Pedidos`. Es la memoria de idempotencia: un pedido ya descontado no vuelve a descontar. |
| Separar movimientos | Split Out | — |
| Sheets · Kardex | Google Sheets | operación `append`, pestaña `Kardex` |
| Separar productos a actualizar | Split Out | — |
| Sheets · Actualizar inventario | Google Sheets | operación `update`, pestaña `Inventario` |
| WooCommerce · Actualizar stock | HTTP Request | salida de error, 3 intentos. La hoja es la fuente de verdad (también descuenta ventas de la tienda física); aquí se copia el stock a la tienda online. |
| Telegram · Falló la tienda | Telegram | — |
| Separar alertas | Split Out | — |
| Telegram · Alerta de stock | Telegram | — |

</details>

<sub>Tablas generadas del JSON del workflow con <code>python scripts/documentar_workflow.py workflows/tienda_produccion.json</code>.</sub>

---

## Demo

<!-- VIDEO: arrastra aquí el .mp4 al editar el README en GitHub y deja solo la URL que genera. -->

<p align="center"><img src="docs/demo_tienda.png" alt="Tienda de demostración conectada a n8n" width="820"></p>

<p align="center"><i>La tienda de demostración conectada al workflow de n8n: se venden las
últimas tazas, un reenvío del mismo aviso se ignora, una cancelación devuelve
stock y un pedido con firma falsa se rechaza.</i></p>

---

## Tres problemas que un flujo ingenuo no ve

Términos que conviene conocer:

- **Webhook:** el aviso que WooCommerce envía automáticamente a una URL cada vez que un pedido cambia.
- **Firma HMAC-SHA256:** WooCommerce calcula un código a partir del contenido del aviso y una clave secreta que solo conocen la tienda y n8n. Si alguien cambia un solo carácter o no tiene la clave, el código no coincide.
- **Idempotencia:** procesar el mismo aviso dos veces da el mismo resultado que procesarlo una vez.
- **Kardex:** el registro de cada entrada y salida de stock, con el pedido que la causó.

| Problema | Qué pasaría sin cuidarlo | Qué hace este flujo |
| --- | --- | --- |
| WooCommerce **reintenta** el aviso si no recibe respuesta, y manda uno nuevo cada vez que alguien toca el pedido | Cada aviso descuenta otra vez y el inventario se vacía solo | El stock se mueve **una vez por pedido**. El estado de cada pedido queda guardado en la hoja |
| Cualquiera que conozca la URL del webhook puede **inventar pedidos** | Un pedido falso descuenta stock real | Se verifica la **firma** sobre el cuerpo exacto; sin firma válida responde 401 y no toca nada |
| Un pedido se **cancela sin haber pagado** | Se "devuelve" stock que nunca salió y el inventario se infla | Solo se devuelve si antes se había descontado |

---

## Pruebas

<p align="center"><img src="docs/pruebas.png" alt="Resultados de las pruebas automáticas y de la verificación en n8n real" width="900"></p>

La integración continua corre todos los tests en cada push. Lo de la columna
derecha se verificó importando los workflows en n8n 2.40 con Docker.

---

## Probarlo en 2 minutos

```bash
pip install pytest
python scripts/simular_dia.py        # 17 avisos de un día, con sus decisiones
python -m pytest -v                  # 49 tests
```

También puedes abrir `demo/index.html` con doble clic: en modo simulado
funciona sin instalar nada.

**Con n8n de verdad** (Docker):

```bash
docker compose up -d
docker exec tienda_n8n n8n import:workflow --input=/workflows/tienda_demo.json
docker exec tienda_n8n n8n update:workflow --id=tiendademo --active=true
docker restart tienda_n8n
```

En la demo elige **n8n real**: cada botón firma el aviso en el navegador y lo
manda al workflow. La configuración de producción (WooCommerce, Google Sheets y
Telegram) está en [`GUIA.md`](GUIA.md).

---

## Cómo se mide que funciona

`scripts/generar_eventos.py` escribe un día de 17 avisos firmados, uno por
cada situación difícil, con la decisión esperada:

| Situación | Decisión |
| --- | --- |
| Pedido pagado | Descontar |
| Mismo aviso reintentado, o reenviado con otro formato de JSON | Ignorar |
| Pedido pagado y luego completado | Descontar una sola vez |
| Cancelado o reembolsado después de pagar | Devolver |
| Cancelado sin haber pagado | Ignorar |
| Se venden las últimas unidades, o más de las que hay | Descontar + alerta de agotado o sobreventa |
| Pedido con un SKU que no está en el inventario | Descontar el resto + alerta |
| Firma falsa, o cuerpo alterado después de firmar | Rechazar con 401 |
| Aviso de prueba que manda WooCommerce al crear el webhook | Ignorar sin error |

Resultado: **17 de 17** decisiones correctas, en Python y en n8n real (los 17
avisos se enviaron por HTTP al workflow y el stock final coincidió con la
simulación). Un test comprueba además que el stock final sea exactamente el
inicial más la suma del kardex.

---

### El detalle que más cuesta ver

La firma se calcula sobre los **bytes exactos** que mandó WooCommerce. Si n8n
interpreta el JSON y lo vuelve a convertir en texto, cambian los espacios y la
firma ya no coincide, aunque el pedido sea legítimo. Por eso el webhook guarda
el cuerpo crudo (*Raw Body*) y un nodo *Extract from File* lo convierte en
texto sin tocarlo, antes de verificar nada.

La lógica existe dos veces, en Python y en el nodo Code de n8n. Un test
**ejecuta el nodo fuera de n8n** y compara aviso por aviso, incluidos cantidades
como `"2"`, `2.0` o `true`, que un lenguaje acepta y el otro no si no se cuida.

---

## Estructura

```
├── data/
│   ├── inventario.json              # 10 productos de una tostaduría ficticia
│   └── eventos.json                 # 17 avisos firmados con la decisión esperada
├── src/sync_tienda.py               # firma, idempotencia, movimientos y alertas
├── workflows/
│   ├── src/sincronizar_pedido.js    # el código del nodo de n8n
│   ├── tienda_demo.json             # importable, corre SIN credenciales
│   └── tienda_produccion.json       # WooCommerce + Google Sheets + Telegram
├── demo/                            # tienda de prueba: simulada o conectada a n8n
├── scripts/                         # generador de avisos, simulación y build
├── tests/                           # 49 tests (incluye paridad JS ↔ Python)
└── docker-compose.yml               # n8n self-hosted
```

---

## Flujo de trabajo con Git

El repositorio sigue **Git Flow**: `main` siempre desplegable, `develop` como
integración, y una rama por cambio. Los merges son `--no-ff` para que cada
funcionalidad quede como un bloque legible en el historial, y cada versión
lleva su tag.

```mermaid
gitGraph
   commit id: "chore: set up the repository"
   branch develop
   checkout develop
   branch feature/motor-stock
   checkout feature/motor-stock
   commit id: "feat: move stock once per WooCommerce order"
   commit id: "test: cover signatures, idempotency, refunds ..."
   checkout develop
   merge feature/motor-stock
   branch feature/dia-de-pedidos
   checkout feature/dia-de-pedidos
   commit id: "feat: generate a day of signed WooCommerce de..."
   commit id: "feat: simulate the day and print decisions, a..."
   commit id: "test: final stock must equal the initial stoc..."
   checkout develop
   merge feature/dia-de-pedidos
   branch feature/nodo-n8n
   checkout feature/nodo-n8n
   commit id: "feat: port the stock logic to the n8n Code node"
   commit id: "test: run the n8n node outside n8n and compar..."
   checkout develop
   merge feature/nodo-n8n
   branch feature/workflows
   checkout feature/workflows
   commit id: "feat: build the demo and production workflows"
   commit id: "test: check the workflows keep the raw body, ..."
   checkout develop
   merge feature/workflows
   branch feature/demo-tienda
   checkout feature/demo-tienda
   commit id: "feat: add a demo store that fires signed deli..."
   commit id: "docs: add a screenshot of the demo store driv..."
   checkout develop
   merge feature/demo-tienda
   branch chore/ci
   checkout chore/ci
   commit id: "chore: run tests and the day simulation on ev..."
   checkout develop
   merge chore/ci
   branch docs/documentacion
   checkout docs/documentacion
   commit id: "docs: explain the three problems a naive stoc..."
   commit id: "docs: add the production guide and known limits"
   checkout develop
   merge docs/documentacion
   branch release/v1.0.0
   checkout release/v1.0.0
   commit id: "chore(release): prepare v1.0.0"
   checkout main
   merge release/v1.0.0 tag: "v1.0.0"
   checkout develop
   merge release/v1.0.0
   branch docs/imagenes-readme
   checkout docs/imagenes-readme
   commit id: "docs: add architecture and test result images..."
   checkout develop
   merge docs/imagenes-readme
   branch release/v1.1.0
   checkout release/v1.1.0
   commit id: "chore(release): prepare v1.1.0"
   checkout main
   merge release/v1.1.0 tag: "v1.1.0"
   checkout develop
   merge release/v1.1.0
   branch feature/diagrama-git
   checkout feature/diagrama-git
   commit id: "feat: draw the Git Flow history as a Mermaid ..."
   checkout develop
   merge feature/diagrama-git
   branch docs/diagrama-git-flow
   checkout docs/diagrama-git-flow
   commit id: "docs: show the branch history as a gitGraph i..."
   checkout develop
   merge docs/diagrama-git-flow
   branch release/v1.1.1
   checkout release/v1.1.1
   commit id: "chore(release): prepare v1.1.1"
   checkout main
   merge release/v1.1.1 tag: "v1.1.1"
   checkout develop
   merge release/v1.1.1
   branch feature/canvas-ordenado
   checkout feature/canvas-ordenado
   commit id: "feat: lay out the canvas from the workflow co..."
   checkout develop
   merge feature/canvas-ordenado
   branch feature/documentar-workflow
   checkout feature/documentar-workflow
   commit id: "feat: document the n8n techniques each workfl..."
   checkout develop
   merge feature/documentar-workflow
```

<p align="center"><i>Historial real del repositorio, generado con
<code>python scripts/diagrama_git.py</code>.</i></p>

| Rama | Para qué |
| --- | --- |
| `main` | Solo versiones liberadas. Cada merge lleva su tag. |
| `develop` | Integración de todo lo terminado. |
| `feature/*` | Una funcionalidad nueva. |
| `fix/*` | Una corrección concreta. |
| `release/*` | Preparación de la versión; luego se fusiona a `main` y `develop`. |

Los mensajes siguen [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `test:`, `docs:`, `chore:`, con el porqué del cambio en el cuerpo.

---

## Documentación

| Documento | Contenido |
| --- | --- |
| [`GUIA.md`](GUIA.md) | Puesta en producción, arquitectura, límites y problemas de n8n encontrados al probar |
| [`CHANGELOG.md`](CHANGELOG.md) | Cambios por versión |

---

## Licencia

[MIT](LICENSE) · Daniel Yataco Blas

> Proyecto de demostración construido con **datos ficticios**. La tienda, sus
> productos y los pedidos no existen. La clave de firma de la demo es pública
> a propósito; en producción se usa la de WooCommerce.
