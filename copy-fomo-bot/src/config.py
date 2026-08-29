"""Carga la configuracion desde config/config.yaml (+ overrides por .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass
class WalletCfg:
    address: str
    label: str


@dataclass
class Config:
    solana_wallets: list[WalletCfg]
    bnb_wallets: list[WalletCfg]

    mode: str
    starting_balance_usd: float
    capital_per_trade_usd: float
    take_profit_pct: float
    stop_loss_pct: float
    max_open_positions: int
    ignore_tokens_bnb: set[str]

    solana_interval_sec: int
    bnb_interval_sec: int
    price_check_interval_sec: int
    status_print_interval_sec: int

    helius_api_key: str
    solana_rpc_url: str
    bscscan_api_key: str

    trades_csv: str
    state_file: str

    raw: dict = field(default_factory=dict)


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else ROOT / "config" / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"No existe {cfg_path}. Copia config/config.example.yaml a "
            f"config/config.yaml y rellena tus wallets/keys."
        )

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def wallets(chain: str) -> list[WalletCfg]:
        items = (raw.get("wallets") or {}).get(chain) or []
        return [WalletCfg(address=i["address"], label=i.get("label", chain)) for i in items]

    trading = raw.get("trading") or {}
    polling = raw.get("polling") or {}
    api = raw.get("api") or {}
    logging_cfg = raw.get("logging") or {}

    helius_key = os.getenv("HELIUS_API_KEY") or api.get("helius_api_key") or ""
    bscscan_key = os.getenv("BSCSCAN_API_KEY") or api.get("bscscan_api_key") or ""

    return Config(
        solana_wallets=wallets("solana"),
        bnb_wallets=wallets("bnb"),
        mode=trading.get("mode", "paper"),
        starting_balance_usd=float(trading.get("starting_balance_usd", 500)),
        capital_per_trade_usd=float(trading.get("capital_per_trade_usd", 100)),
        take_profit_pct=float(trading.get("take_profit_pct", 25)),
        stop_loss_pct=float(trading.get("stop_loss_pct", 15)),
        max_open_positions=int(trading.get("max_open_positions", 10)),
        ignore_tokens_bnb={a.lower() for a in (trading.get("ignore_tokens_bnb") or [])},
        solana_interval_sec=int(polling.get("solana_interval_sec", 15)),
        bnb_interval_sec=int(polling.get("bnb_interval_sec", 15)),
        price_check_interval_sec=int(polling.get("price_check_interval_sec", 20)),
        status_print_interval_sec=int(polling.get("status_print_interval_sec", 60)),
        helius_api_key=helius_key,
        solana_rpc_url=api.get("solana_rpc_url", "https://api.mainnet-beta.solana.com"),
        bscscan_api_key=bscscan_key,
        trades_csv=logging_cfg.get("trades_csv", "logs/trades.csv"),
        state_file=logging_cfg.get("state_file", "logs/state.json"),
        raw=raw,
    )
