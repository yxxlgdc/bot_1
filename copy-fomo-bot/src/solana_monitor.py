"""Detecta compras (swaps SOL -> token) de una wallet en Solana.

Dos modos:
  - Con HELIUS_API_KEY: usa la Enhanced Transactions API de Helius, que ya
    viene con los swaps parseados (recomendado, mucho mas fiable).
  - Sin key: hace polling directo al RPC publico y aplica una heuristica
    sobre los cambios de balance (preTokenBalances/postTokenBalances) para
    adivinar si la transaccion fue una compra. Es menos fiable y esta sujeta
    a rate limits del RPC publico.
"""
from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from src.config import Config
from src.logger_setup import get_logger
from src.trade_log import TradeStore

log = get_logger("solana_monitor")

HELIUS_TX_URL = "https://api.helius.xyz/v0/addresses/{address}/transactions"

# Wrapped SOL mint, usado para descartar "swaps" SOL->SOL
WSOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class BuySignal:
    chain: str
    token_address: str
    token_symbol: str
    source_label: str
    chain_ts: float | None = None  # timestamp unix (segundos) de la transaccion en la cadena


async def _poll_helius(
    session: aiohttp.ClientSession, cfg: Config, wallet: str, label: str, store: TradeStore
) -> list[BuySignal]:
    url = HELIUS_TX_URL.format(address=wallet)
    params = {"api-key": cfg.helius_api_key, "limit": "20"}
    signals: list[BuySignal] = []
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning(f"Helius devolvio HTTP {resp.status} para {label}")
                return signals
            txs = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning(f"Fallo consultando Helius para {label}: {e}")
        return signals

    # Helius devuelve las mas recientes primero
    for tx in reversed(txs):
        sig = tx.get("signature")
        if not sig or store.is_solana_sig_seen(wallet, sig):
            continue
        store.mark_solana_sig_seen(wallet, sig)

        swap = (tx.get("events") or {}).get("swap")
        if not swap:
            continue

        native_input = swap.get("nativeInput")
        token_outputs = swap.get("tokenOutputs") or []
        if not native_input or not token_outputs:
            # No es un SOL -> token swap (podria ser token->SOL, es decir una venta)
            continue

        out = token_outputs[0]
        mint = out.get("mint")
        if not mint or mint == WSOL_MINT:
            continue

        chain_ts = tx.get("timestamp")  # Helius: unix seconds
        signals.append(BuySignal("solana", mint, mint[:6], label, chain_ts=chain_ts))

    store.save_state()
    return signals


async def _poll_raw_rpc(
    session: aiohttp.ClientSession, cfg: Config, wallet: str, label: str, store: TradeStore
) -> list[BuySignal]:
    signals: list[BuySignal] = []

    sig_resp = await _rpc_call(
        session, cfg.solana_rpc_url, "getSignaturesForAddress", [wallet, {"limit": 15}]
    )
    if sig_resp is None:
        return signals
    sigs = [s["signature"] for s in sig_resp if not s.get("err")]

    for sig in reversed(sigs):
        if store.is_solana_sig_seen(wallet, sig):
            continue
        store.mark_solana_sig_seen(wallet, sig)

        tx = await _rpc_call(
            session,
            cfg.solana_rpc_url,
            "getTransaction",
            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        if not tx or not tx.get("meta"):
            continue

        signal = _heuristic_detect_buy(tx, wallet, label)
        if signal:
            signals.append(signal)  # ya trae chain_ts desde blockTime

    store.save_state()
    return signals


async def _rpc_call(session: aiohttp.ClientSession, url: str, method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get("result")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Fallo en llamada RPC {method}: {e}")
        return None


def _heuristic_detect_buy(tx: dict, wallet: str, label: str) -> BuySignal | None:
    """Heuristica: SOL nativo del wallet baja (mas que la fee) y el balance de
    algun token SPL del wallet sube -> probablemente una compra."""
    meta = tx["meta"]
    chain_ts = tx.get("blockTime")  # unix seconds, puede venir null en algunos RPC
    account_keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
    try:
        idx = account_keys.index(wallet)
    except ValueError:
        return None

    pre_sol = meta["preBalances"][idx]
    post_sol = meta["postBalances"][idx]
    fee = meta.get("fee", 0)
    sol_spent = (pre_sol - post_sol - fee) / 1e9
    if sol_spent <= 0:
        return None  # no gasto SOL neto (aparte de la fee) -> no parece una compra

    pre_tokens = {b["mint"]: b for b in meta.get("preTokenBalances", []) if b.get("owner") == wallet}
    post_tokens = {b["mint"]: b for b in meta.get("postTokenBalances", []) if b.get("owner") == wallet}

    for mint, post_b in post_tokens.items():
        if mint == WSOL_MINT:
            continue
        pre_amount = float((pre_tokens.get(mint) or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
        post_amount = float(post_b.get("uiTokenAmount", {}).get("uiAmount") or 0)
        if post_amount > pre_amount:
            return BuySignal("solana", mint, mint[:6], label, chain_ts=chain_ts)

    return None


async def poll_solana_wallet(
    session: aiohttp.ClientSession, cfg: Config, wallet: str, label: str, store: TradeStore
) -> list[BuySignal]:
    if cfg.helius_api_key:
        return await _poll_helius(session, cfg, wallet, label, store)
    return await _poll_raw_rpc(session, cfg, wallet, label, store)
