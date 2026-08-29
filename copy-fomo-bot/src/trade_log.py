"""Persistencia sencilla: CSV de operaciones cerradas + estado (posiciones abiertas)."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time

CSV_HEADERS = [
    "closed_at", "chain", "token_address", "token_symbol", "source_label",
    "opened_at", "entry_price_usd", "exit_price_usd", "capital_usd",
    "pnl_usd", "pnl_pct", "close_reason", "balance_after",
    "chain_ts", "latency_sec",
]


@dataclass
class Position:
    chain: str
    token_address: str
    token_symbol: str
    source_label: str
    entry_price_usd: float
    capital_usd: float
    opened_at: float = field(default_factory=time)
    # Momento (unix, segundos) en que la wallet original hizo la compra en la
    # cadena, y cuanto tardo el bot en reaccionar (abrir la posicion simulada
    # desde que ocurrio esa transaccion). None si no se pudo determinar.
    chain_ts: float | None = None
    latency_sec: float | None = None

    def key(self) -> str:
        return f"{self.chain}:{self.token_address}"

    def to_dict(self) -> dict:
        return asdict(self)


class TradeStore:
    def __init__(self, csv_path: str, state_path: str, starting_balance: float = 500.0):
        self.csv_path = Path(csv_path)
        self.state_path = Path(state_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_HEADERS)

        self.open_positions: dict[str, Position] = {}
        self.seen_solana_sigs: dict[str, list[str]] = {}
        self.seen_bnb_tx: dict[str, list[str]] = {}
        # Efectivo disponible (NO incluye el capital ya comprometido en posiciones
        # abiertas: eso se descuenta al abrir y se devuelve -con su pnl- al cerrar)
        self.balance: float = starting_balance
        self._load_state(starting_balance)

    def _load_state(self, starting_balance: float) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for k, v in (data.get("open_positions") or {}).items():
            self.open_positions[k] = Position(**v)
        self.seen_solana_sigs = data.get("seen_solana_sigs") or {}
        self.seen_bnb_tx = data.get("seen_bnb_tx") or {}
        # Si ya habia un estado guardado, respeta el balance que traia;
        # si es la primera vez que se ve este state file, usa el balance inicial.
        self.balance = data.get("balance", starting_balance)

    def save_state(self) -> None:
        data = {
            "balance": self.balance,
            "open_positions": {k: v.to_dict() for k, v in self.open_positions.items()},
            "seen_solana_sigs": self.seen_solana_sigs,
            "seen_bnb_tx": self.seen_bnb_tx,
        }
        self.state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def open_position(self, pos: Position) -> None:
        self.open_positions[pos.key()] = pos
        self.balance -= pos.capital_usd  # ese dinero queda "bloqueado" en la posicion
        self.save_state()

    def close_position(self, key: str, exit_price_usd: float, close_reason: str) -> dict | None:
        pos = self.open_positions.pop(key, None)
        if pos is None:
            return None
        pnl_pct = (exit_price_usd / pos.entry_price_usd - 1) * 100 if pos.entry_price_usd else 0.0
        pnl_usd = pos.capital_usd * (pnl_pct / 100)
        # Se devuelve el capital que se habia bloqueado, mas (o menos) el resultado
        self.balance += pos.capital_usd + pnl_usd
        row = {
            "closed_at": time(),
            "chain": pos.chain,
            "token_address": pos.token_address,
            "token_symbol": pos.token_symbol,
            "source_label": pos.source_label,
            "opened_at": pos.opened_at,
            "entry_price_usd": pos.entry_price_usd,
            "exit_price_usd": exit_price_usd,
            "capital_usd": pos.capital_usd,
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 2),
            "close_reason": close_reason,
            "balance_after": round(self.balance, 4),
            "chain_ts": pos.chain_ts,
            "latency_sec": round(pos.latency_sec, 2) if pos.latency_sec is not None else None,
        }
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)
        self.save_state()
        return row

    def mark_solana_sig_seen(self, wallet: str, sig: str, keep_last: int = 200) -> None:
        lst = self.seen_solana_sigs.setdefault(wallet, [])
        lst.append(sig)
        if len(lst) > keep_last:
            del lst[:-keep_last]

    def is_solana_sig_seen(self, wallet: str, sig: str) -> bool:
        return sig in self.seen_solana_sigs.get(wallet, [])

    def mark_bnb_tx_seen(self, wallet: str, tx_hash: str, keep_last: int = 200) -> None:
        lst = self.seen_bnb_tx.setdefault(wallet, [])
        lst.append(tx_hash)
        if len(lst) > keep_last:
            del lst[:-keep_last]

    def is_bnb_tx_seen(self, wallet: str, tx_hash: str) -> bool:
        return tx_hash in self.seen_bnb_tx.get(wallet, [])
