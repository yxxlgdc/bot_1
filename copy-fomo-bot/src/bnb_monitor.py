"""Detecta compras de tokens BEP-20 de una wallet en BNB Chain via BscScan.

Heuristica: se considera "compra" cualquier transferencia BEP-20 ENTRANTE a la
wallet objetivo cuyo token NO este en la lista `ignore_tokens_bnb` (WBNB,
BUSD, USDT, etc.). La idea es que al comprar un token con BNB/una stablecoin,
el token nuevo entra en la wallet; al vender, es la stablecoin/BNB lo que
entra (y por tanto se ignora). No es perfecto (transferencias entre wallets
propias, airdrops, etc. pueden generar falsos positivos) pero es un buen
punto de partida - ajusta `ignore_tokens_bnb` en config.yaml segun lo que veas.
"""
from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from src.config import Config
from src.logger_setup import get_logger
from src.trade_log import TradeStore

log = get_logger("bnb_monitor")

BSCSCAN_URL = "https://api.bscscan.com/api"


@dataclass
class BuySignal:
    chain: str
    token_address: str
    token_symbol: str
    source_label: str
    chain_ts: float | None = None  # timestamp unix (segundos) de la transaccion en la cadena


async def poll_bnb_wallet(
    session: aiohttp.ClientSession, cfg: Config, wallet: str, label: str, store: TradeStore
) -> list[BuySignal]:
    signals: list[BuySignal] = []

    if not cfg.bscscan_api_key:
        log.warning(
            "No hay BSCSCAN_API_KEY configurada: el monitor de BNB Chain no puede "
            "consultar el historial de transacciones. Consigue una key gratuita en "
            "https://bscscan.com/apis"
        )
        return signals

    params = {
        "module": "account",
        "action": "tokentx",
        "address": wallet,
        "sort": "desc",
        "page": "1",
        "offset": "20",
        "apikey": cfg.bscscan_api_key,
    }
    try:
        async with session.get(BSCSCAN_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning(f"BscScan devolvio HTTP {resp.status} para {label}")
                return signals
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning(f"Fallo consultando BscScan para {label}: {e}")
        return signals

    if data.get("status") != "1":
        # status "0" con message "No transactions found" es normal para wallets nuevas
        if data.get("message") not in ("No transactions found", "OK"):
            log.warning(f"BscScan respondio con error para {label}: {data.get('message')}")
        return signals

    txs = data.get("result") or []

    for tx in reversed(txs):
        tx_hash = tx.get("hash")
        if not tx_hash or store.is_bnb_tx_seen(wallet, tx_hash):
            continue
        store.mark_bnb_tx_seen(wallet, tx_hash)

        to_addr = (tx.get("to") or "").lower()
        if to_addr != wallet.lower():
            continue  # no es una transferencia entrante, no interesa como señal de compra

        contract = (tx.get("contractAddress") or "").lower()
        if not contract or contract in cfg.ignore_tokens_bnb:
            continue

        symbol = tx.get("tokenSymbol") or contract[:6]
        try:
            chain_ts = float(tx.get("timeStamp")) if tx.get("timeStamp") else None
        except (TypeError, ValueError):
            chain_ts = None
        signals.append(BuySignal("bnb", tx.get("contractAddress"), symbol, label, chain_ts=chain_ts))

    store.save_state()
    return signals
