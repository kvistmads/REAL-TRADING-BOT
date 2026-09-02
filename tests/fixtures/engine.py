"""
En TradingEngine med alle I/O-kanter erstattet af fakes.

Til tests der skal køre et helt _tick() igennem uden netværk, DB eller Telegram.
Kun engine-logikken (indikator-bundle, gates, signal-flow) er ægte.
"""
from __future__ import annotations

import pandas as pd

from core.engine import TradingEngine
from core.time_utils import utc_now

CONFIG = {
    "exchange": {"name": "binance", "sandbox": True},
    "trading": {"dry_run": True, "total_capital": 100.0, "stake_amount": 5.0,
                "max_open_trades": 4, "leverage": 1, "breakeven_trigger_pct": 0.5,
                "max_bars_held": 24},
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "timeframes": {"primary": "4h", "entry": "1h"},
    "strategies": {"enabled": [], "min_confidence": 0.45},
    "gates": {"confluence": {"enabled": False}, "risk": {"enabled": False},
              "regime": {"enabled": False}},
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0,
                   "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0,
                  "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0,
                 "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
    },
}


class _Tracker:
    def __init__(self):
        # Hvad engine'en sendte til flip-tjekket. Engine'en sluger fejl her (best-effort
        # instrumentering), så uden en rigtig metode ville en signatur-ændring aldrig
        # blive fanget af testene — den ville bare stille holde op med at virke.
        self.flip_calls: list[dict] = []

    def get_open_positions(self): return []
    def get_open_count(self): return 0
    def get_daily_pnl(self): return 0.0
    async def check_breakeven(self, prices): return []
    async def check_sl_tp(self, prices): return []
    async def check_time_stop(self, prices, max_bars, bar_seconds): return []

    async def check_flip_levels(self, closed_bars):
        self.flip_calls.append(closed_bars)
        return []


class _Fetcher:
    def __init__(self, bars: dict[str, pd.DataFrame], prices: dict[str, float]):
        self._bars = bars
        self._prices = prices

    async def get_latest_price(self, symbol): return self._prices.get(symbol)
    async def get_multi(self, symbols, timeframe):
        return {s: self._bars[s] for s in symbols if s in self._bars}


class _Notifier:
    async def send_trade_closed(self, trade, reason): pass
    async def send_trade_opened(self, trade, confidence): pass
    async def send_gate_rejected(self, signal, result): pass
    async def send_daily_summary(self, stats): pass


def fake_engine(monkeypatch, strategies: list, bars: dict[str, pd.DataFrame],
                prices: dict[str, float] | None = None,
                config: dict | None = None) -> TradingEngine:
    cfg = config or {**CONFIG, "symbols": list(bars)}
    engine = TradingEngine(cfg)
    engine.strategies = strategies
    engine.position_tracker = _Tracker()
    engine.fetcher = _Fetcher(bars, prices or {s: 100.0 for s in bars})
    engine.notifier = _Notifier()
    engine.gates = []
    # Ingen dashboard-skrivning, ingen daglig summary og ingen DB-logning.
    monkeypatch.setattr(engine, "_write_dashboard_status", _noop)
    monkeypatch.setattr(engine, "_log_signal", _noop3)
    engine._last_summary_date = utc_now().date()
    return engine


async def _noop(*args, **kwargs): pass
async def _noop3(signal, gate_passed, trade_id): pass
