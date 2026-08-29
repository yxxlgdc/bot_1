"""Punto de entrada del bot: orquesta los monitores de wallets y el motor de
paper trading. Modo simulacion unicamente (ver README para el aviso sobre
trading real)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bnb_monitor import poll_bnb_wallet
from src.config import load_config
from src.logger_setup import get_logger
from src.paper_trader import PaperTrader
from src.solana_monitor import poll_solana_wallet
from src.trade_log import TradeStore

log = get_logger("main")


async def solana_loop(session, cfg, store, trader):
    if not cfg.solana_wallets:
        return
    while True:
        for w in cfg.solana_wallets:
            try:
                signals = await poll_solana_wallet(session, cfg, w.address, w.label, store)
                for s in signals:
                    await trader.on_buy_signal(
                        session, s.chain, s.token_address, s.token_symbol, s.source_label, chain_ts=s.chain_ts
                    )
            except Exception as e:  # noqa: BLE001 - un fallo puntual no debe tumbar el bot
                log.exception(f"Error monitorizando wallet Solana {w.label}: {e}")
        await asyncio.sleep(cfg.solana_interval_sec)


async def bnb_loop(session, cfg, store, trader):
    if not cfg.bnb_wallets:
        return
    while True:
        for w in cfg.bnb_wallets:
            try:
                signals = await poll_bnb_wallet(session, cfg, w.address, w.label, store)
                for s in signals:
                    await trader.on_buy_signal(
                        session, s.chain, s.token_address, s.token_symbol, s.source_label, chain_ts=s.chain_ts
                    )
            except Exception as e:  # noqa: BLE001
                log.exception(f"Error monitorizando wallet BNB {w.label}: {e}")
        await asyncio.sleep(cfg.bnb_interval_sec)


async def price_check_loop(session, cfg, trader):
    while True:
        await asyncio.sleep(cfg.price_check_interval_sec)
        try:
            await trader.check_positions(session)
        except Exception as e:  # noqa: BLE001
            log.exception(f"Error comprobando posiciones abiertas: {e}")


async def status_loop(cfg, trader):
    while True:
        await asyncio.sleep(cfg.status_print_interval_sec)
        trader.print_summary()


async def run() -> None:
    cfg = load_config()

    if cfg.mode != "paper":
        log.error(
            "trading.mode distinto de 'paper' en config.yaml. Esta version del bot "
            "SOLO soporta simulacion (paper trading) por seguridad. Deteniendo."
        )
        return

    if not cfg.solana_wallets and not cfg.bnb_wallets:
        log.error("No hay ninguna wallet configurada en config.yaml (wallets.solana / wallets.bnb). Nada que hacer.")
        return

    store = TradeStore(cfg.trades_csv, cfg.state_file, starting_balance=cfg.starting_balance_usd)
    trader = PaperTrader(cfg, store)

    log.info("Bot de copy-trading (SIMULACION) iniciado")
    log.info(f"  Wallets Solana: {[w.address for w in cfg.solana_wallets] or 'ninguna'}")
    log.info(f"  Wallets BNB Chain: {[w.address for w in cfg.bnb_wallets] or 'ninguna'}")
    log.info(
        f"  Balance inicial: ${cfg.starting_balance_usd} | Capital por operacion (max): ${cfg.capital_per_trade_usd} | "
        f"TP: +{cfg.take_profit_pct}% | SL: -{cfg.stop_loss_pct}%"
    )

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            solana_loop(session, cfg, store, trader),
            bnb_loop(session, cfg, store, trader),
            price_check_loop(session, cfg, trader),
            status_loop(cfg, trader),
        )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Detenido por el usuario.")
