"""Obtiene el precio USD de un token via la API publica de DexScreener.

DexScreener cubre Solana y BNB Chain (y muchas mas) sin necesidad de API key,
lo que lo hace comodo para el paper trading. Para uso en real/alto volumen,
conviene moverse a Birdeye (Solana) / un nodo propio + oraculo de precio.
"""
from __future__ import annotations

import aiohttp

from src.logger_setup import get_logger

log = get_logger("price_feed")

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# DexScreener identifica las chains con estos ids
CHAIN_IDS = {
    "solana": "solana",
    "bnb": "bsc",
}


async def get_price_usd(session: aiohttp.ClientSession, chain: str, token_address: str) -> float | None:
    """Devuelve el precio USD del token, o None si no se encuentra ningun par."""
    url = DEXSCREENER_TOKEN_URL.format(address=token_address)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception as e:  # noqa: BLE001 - red poco fiable, no debe tumbar el bot
        log.warning(f"price_feed: fallo consultando {token_address[:8]}...: {e}")
        return None

    pairs = data.get("pairs") or []
    chain_id = CHAIN_IDS.get(chain)
    candidates = [p for p in pairs if p.get("chainId") == chain_id] if chain_id else pairs
    if not candidates:
        return None

    # Coge el par con mayor liquidez para evitar precios de pools ilíquidos
    def liquidity(p: dict) -> float:
        try:
            return float((p.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    best = max(candidates, key=liquidity)
    price = best.get("priceUsd")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None
