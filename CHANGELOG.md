# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y versionado [SemVer](https://semver.org/lang/es/).

## [1.1.1]

### Añadido
- Diagrama gitGraph del historial en el README, generado por `scripts/diagrama_git.py` a partir de las ramas y tags reales.

## [1.1.0]

### Añadido
- Imagen de arquitectura en el README: problema, entradas, pasos dentro de n8n y salidas.
- Imagen de pruebas en el README: tests por archivo y verificaciones hechas en n8n real.

## [1.0.0]

### Añadido
- Verificación de la firma HMAC-SHA256 de cada aviso de WooCommerce sobre el cuerpo exacto.
- Movimiento de stock una sola vez por pedido: reintentos y avisos repetidos se ignoran.
- Devolución de stock al cancelar o reembolsar, solo si el pedido había descontado.
- Alertas de stock bajo, agotado, sobreventa y SKU desconocido.
- Workflow demo sin credenciales y workflow de producción con Google Sheets (inventario, pedidos y kardex), actualización de stock en WooCommerce con reintentos, y Telegram.
- Tienda de demostración con modo simulado y modo conectado a n8n.
- Día de 17 avisos de prueba con el resultado esperado de cada uno.
- Test de paridad entre el nodo JavaScript y la lógica Python.
