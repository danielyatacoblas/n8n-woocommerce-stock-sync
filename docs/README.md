# docs

Material de apoyo del repositorio.

- `demo_tienda.png`: la tienda de demostración conectada al workflow de n8n, después de vender las últimas tazas, reenviar un aviso, cancelar un pedido y mandar un pedido falso.

## Grabar el video de la demo

1. `docker compose up -d` e importa y activa `workflows/tienda_demo.json` (ver README).
2. Abre `demo/index.html`, elige **n8n real** y pon n8n a un lado en la pestaña *Executions*.
3. En este orden:
   - Taza: **Comprar 3** → se agota (alerta).
   - Taza: **Comprar 1** → sobreventa (alerta en rojo).
   - En ese último pedido, **Reenviar aviso** → ignorado: no descuenta dos veces.
   - **Cancelar** ese pedido → la taza vuelve al stock.
   - **Pedido falso** → rechazado con 401 y el stock no se mueve.
4. Guarda el archivo como `docs/video.mp4`. Luego, al editar el README en
   GitHub, arrastra el video donde dice `VIDEO` para que se reproduzca en la página.
