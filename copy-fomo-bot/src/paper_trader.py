"""Motor de paper trading: abre posiciones simuladas al recibir una señal de
compra, y las cierra al alcanzar el take-profit o el stop-loss."""
from __future__ import annotations

from time import time

import aiohttp

from src.config import Config
from src.logger_setup import get_logger
from src.price_feed import get_price_usd
from src.trade_log import Position, TradeStore

log = get_logger("paper_trader")


class PaperTrader:
    def __init__(self, cfg: Config, store: TradeStore):
        self.cfg = cfg
        self.store = store

    async def on_buy_signal(
        self,
        session: aiohttp.ClientSession,
        chain: str,
        token_address: str,
        token_symbol: str,
        source_label: str,
        chain_ts: float | None = None,
    ) -> None:
        key = f"{chain}:{token_address}"
        if key in self.store.open_positions:
            log.info(f"Ya hay una posicion abierta para {token_symbol} ({chain}), se ignora la señal duplicada")
            return
        if len(self.store.open_positions) >= self.cfg.max_open_positions:
            log.warning("Limite de posiciones abiertas alcanzado, se ignora la señal")
            return

        if self.store.balance <= 0:
            log.warning(f"Sin capital disponible (balance ${self.store.balance:.2f}), se ignora la señal")
            return

        price = await get_price_usd(session, chain, token_address)
        if price is None or price <= 0:
            log.warning(f"No se pudo obtener precio para {token_symbol} ({token_address}), se ignora la señal")
            return

        # Nunca se arriesga mas de lo que queda de banca: si hay menos que el
        # tamano habitual de operacion, se opera con lo que quede.
        capital_usd = min(self.cfg.capital_per_trade_usd, self.store.balance)

        now = time()
        latency_sec = (now - chain_ts) if chain_ts else None

        pos = Position(
            chain=chain,
            token_address=token_address,
            token_symbol=token_symbol,
            source_label=source_label,
            entry_price_usd=price,
            capital_usd=capital_usd,
            opened_at=now,
            chain_ts=chain_ts,
            latency_sec=latency_sec,
        )
        self.store.open_position(pos)

        latency_msg = f"{latency_sec:.1f}s desde la tx original" if latency_sec is not None else "desconocida (sin timestamp de la tx)"
        log.info(
            f"[COMPRA SIMULADA] {token_symbol} ({chain}) @ ${price:.8f} | "
            f"capital ${pos.capital_usd:.2f} | copiado de {source_label} | "
            f"balance restante ${self.store.balance:.2f} | latencia: {latency_msg}"
        )

    async def check_positions(self, session: aiohttp.ClientSession) -> None:
        for key in list(self.store.open_positions.keys()):
            pos = self.store.open_positions.get(key)
            if pos is None:
                continue
            price = await get_price_usd(session, pos.chain, pos.token_address)
            if price is None or price <= 0:
                continue

            pct_change = (price / pos.entry_price_usd - 1) * 100 if pos.entry_price_usd else 0.0

            reason = None
            if pct_change >= self.cfg.take_profit_pct:
                reason = "take_profit"
            elif pct_change <= -self.cfg.stop_loss_pct:
                reason = "stop_loss"

            if reason:
                row = self.store.close_position(key, price, reason)
                if row:
                    emoji = "🟢" if row["pnl_usd"] >= 0 else "🔴"
                    log.info(
                        f"[VENTA SIMULADA {emoji}] {pos.token_symbol} ({pos.chain}) "
                        f"@ ${price:.8f} | motivo={reason} | "
                        f"pnl={row['pnl_pct']:.2f}% (${row['pnl_usd']:.2f}) | "
                        f"balance ${row['balance_after']:.2f}"
                    )

    def print_summary(self) -> None:
        n_open = len(self.store.open_positions)
        locked = sum(p.capital_usd for p in self.store.open_positions.values())
        equity = self.store.balance + locked
        log.info(
            f"Balance disponible: ${self.store.balance:.2f} | "
            f"En posiciones abiertas: ${locked:.2f} | "
            f"Equity total: ${equity:.2f} | Posiciones abiertas: {n_open}"
        )
        for pos in self.store.open_positions.values():
            log.info(
                f"  - {pos.token_symbol} ({pos.chain}) entrada=${pos.entry_price_usd:.8f} "
                f"capital=${pos.capital_usd:.2f} fuente={pos.source_label}"
            )
