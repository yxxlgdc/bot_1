# Copy-FOMO Bot (modo simulación)

Bot que vigila una o varias wallets "FOMO" en **Solana** y **BNB Chain**,
detecta cuándo compran un token, y **simula** (paper trading) la misma
compra con un capital fijo por operación. Cada posición simulada se cierra
automáticamente al alcanzar:

- **+25% de beneficio** (take-profit, configurable)
- o **-X% de pérdida** (stop-loss, configurable)

⚠️ **Esta versión solo simula (paper trading). No mueve dinero real ni
firma transacciones.** Es intencional: antes de arriesgar capital real
conviene ver cómo se comporta la estrategia (cuántas señales detecta,
qué % de aciertos tiene, con qué latencia reacciona) con datos reales del
mercado pero sin riesgo. Al final de este documento se explica qué haría
falta añadir para pasar a real.

## 1. Instalación

```bash
cd copy-fomo-bot
python3 -m venv .venv
source .venv/bin/activate      # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configuración

1. Copia la plantilla:
   ```bash
   cp config/config.example.yaml config/config.yaml
   ```
2. Edita `config/config.yaml` y añade la(s) dirección(es) de wallet que
   quieres copiar:
   ```yaml
   wallets:
     solana:
       - address: "DIRECCION_DE_LA_WALLET_SOLANA"
         label: "mi_fomo_favorito"
     bnb:
       - address: "0xDIRECCION_DE_LA_WALLET_BNB"
         label: "otro_trader"
   ```
   Puedes dejar una de las dos listas vacía (`[]`) si solo quieres vigilar
   una cadena.
3. Ajusta si quieres la banca inicial, el capital máximo por operación, el
   take-profit y el stop-loss (por defecto: banca $500, $100 por operación
   -o lo que quede si hay menos-, +25% / -30%).
4. Consigue las API keys gratuitas necesarias y ponlas en `config.yaml` o
   (mejor, para no filtrarlas) en un archivo `.env` (copia `.env.example`):
   - **Helius** (Solana, muy recomendado): https://www.helius.dev — plan
     gratuito de sobra para esto. Sin esta key el bot usa el RPC público de
     Solana con una detección de compras mucho menos fiable (heurística
     basada en cambios de balance).
   - **BscScan** (BNB Chain, obligatorio para que funcione ese monitor):
     https://bscscan.com/apis — el plan gratuito es suficiente.

## 3. Ejecutar

```bash
python -m src.main
```

Verás en consola cada "compra simulada" y "venta simulada" a medida que se
detectan, y cada minuto (configurable) un resumen de las posiciones
abiertas. Todo queda registrado en:

- `logs/trades.csv` — histórico de operaciones cerradas (con P&L).
- `logs/state.json` — estado actual (posiciones abiertas + transacciones ya
  vistas, para no duplicar señales si reinicias el bot).

Puedes dejarlo corriendo en segundo plano (`tmux`, `screen`, un servicio
systemd, etc.) para que vaya acumulando histórico.

## 3b. Dejarlo corriendo 24/7 en un servidor Linux (systemd)

Para que el bot vigile de forma continua (sin depender de que tengas un
`tmux` abierto ni de tu portátil), lo normal es subirlo a un VPS Linux
pequeño y dejarlo como servicio de `systemd`, que lo arranca solo, lo
reinicia si falla, y lo levanta de nuevo si el servidor se reinicia.

1. Sube la carpeta `copy-fomo-bot` al servidor (por ejemplo con `scp` o
   `git clone` si lo subes a un repo) y haz la instalación normal (venv +
   `pip install -r requirements.txt` + `config.yaml`) dentro del servidor.
2. Copia y edita la plantilla de servicio incluida en `deploy/copy-fomo-bot.service`:
   sustituye las tres apariciones de `USUARIO` por el usuario del sistema
   con el que va a correr el bot (evita usar `root`), y las rutas por la
   ruta real donde dejaste el proyecto.
3. Instálalo:
   ```bash
   sudo cp deploy/copy-fomo-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now copy-fomo-bot
   ```
4. Comprueba que está corriendo y mira los logs en vivo:
   ```bash
   sudo systemctl status copy-fomo-bot
   sudo journalctl -u copy-fomo-bot -f
   ```

Con esto, aunque cierres tu Mac o se reinicie el servidor, el bot sigue
vigilando la wallet y registrando operaciones en `logs/trades.csv` dentro
del servidor.

## 4. Cómo detecta las "compras"

- **Solana**: si hay `helius_api_key`, usa la Enhanced Transactions API de
  Helius, que ya identifica los swaps (mucho más fiable). Si no, hace
  polling al RPC público y aplica una heurística: "la wallet gastó SOL neto
  y el balance de algún token SPL le subió" → se interpreta como compra.
- **BNB Chain**: usa BscScan para leer las transferencias BEP-20 de la
  wallet. Cualquier token que **entra** en la wallet y no está en la lista
  `ignore_tokens_bnb` (WBNB/BUSD/USDT por defecto) se interpreta como una
  compra. Añade ahí cualquier otro token que la wallet reciba habitualmente
  sin que sea una "compra" real (por ejemplo, si recibe airdrops).

Estas heurísticas no son perfectas: pueden generar algún falso positivo
(transferencias entre wallets propias del trader, airdrops, etc.). Revisa
`logs/trades.csv` de vez en cuando para afinar `ignore_tokens_bnb` o la
lógica si ves señales raras.

## 5. Pasar a dinero real (no incluido)

Esta versión se ha dejado deliberadamente en modo simulación. Para operar
con fondos reales haría falta, como mínimo:

1. Guardar una clave privada (Solana) o clave privada de una wallet EVM
   (BNB Chain) en un sitio seguro (variable de entorno / gestor de
   secretos, **nunca** en el repo).
2. Añadir la lógica de firma y envío de transacciones: en Solana, construir
   y firmar un swap (p. ej. vía la API de Jupiter); en BNB Chain, firmar y
   enviar una transacción al router de PancakeSwap con `web3.py`.
3. Añadir control de slippage, límites de gas/priority fee, y un límite
   duro de capital total en riesgo.
4. Probar primero con importes muy pequeños.

Dado que esto implica riesgo financiero real y no soy asesor financiero:
antes de dar este paso, considera que copiar operaciones de una wallet
externa no garantiza resultados (esa wallet puede cambiar de estrategia,
salir mal en el timing por la latencia del bot, o directamente ser una
wallet manipulando un token de baja liquidez). Revisa también la normativa
de tu país sobre trading automatizado de criptoactivos.

## Estructura del proyecto

```
copy-fomo-bot/
├── config/
│   └── config.example.yaml   # plantilla de configuración
├── deploy/
│   └── copy-fomo-bot.service # unidad de systemd para correr 24/7 en Linux
├── logs/                     # trades.csv y state.json (se crean solos)
├── src/
│   ├── config.py             # carga config.yaml + .env
│   ├── price_feed.py         # precio USD vía DexScreener
│   ├── solana_monitor.py     # detección de compras en Solana
│   ├── bnb_monitor.py        # detección de compras en BNB Chain
│   ├── paper_trader.py       # abre/cierra posiciones simuladas (TP/SL)
│   ├── trade_log.py          # persistencia (CSV + estado)
│   └── main.py                # orquesta todo
├── requirements.txt
└── .env.example
```
