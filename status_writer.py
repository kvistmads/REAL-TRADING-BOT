"""
status_writer.py — Skriv bot_status.json til dashboard
=======================================================
Tilføj til dit projekt: from status_writer import write_status

Kald write_status(engine, db_session) fra:
  - main.py efter hvert loop-tick  (hvert 30-60s)
  - engine._on_tick() eller lign.

Filen bot_status.json placeres i projektmappen
og hentes af dashboard.html via fetch('./bot_status.json').
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Placer filen ved siden af dashboard.html (eller i projektmappen)
STATUS_FILE = Path(__file__).parent / "bot_status.json"

# Hvor mange datapunkter skal gemmes i historikken?
MAX_HISTORY_POINTS = 500


def write_status(
    *,
    mode: str,           # "dry_run" | "paper" | "live"
    status: str,         # "running" | "stopped" | "error"
    portfolio: dict,     # Se skema nedenfor
    positions: list,
    recent_trades: list,
    regime: dict,
    gates: dict,
    strategies: dict,
    reflection: dict,
    errors: list = None,
):
    """
    Skriv komplet bot-status til bot_status.json.

    portfolio = {
        "total_value": 100.00,
        "cash": 95.00,
        "buying_power": 380.00,
        "open_pnl": 5.00,
        "daily_pnl": 1.50,
        "daily_pnl_pct": 1.5,
        "total_pnl": 1.50,
        "total_pnl_pct": 1.5,
        "win_count": 3,
        "loss_count": 1,
        "profit_factor": 2.1,
        "signals_today": 5,
    }

    positions = [{
        "symbol": "BTC/USDT",
        "side": "buy",
        "qty": 0.0001,
        "entry_price": 45000.00,
        "current_price": 46000.00,
        "pnl": 0.10,
        "pnl_pct": 2.2,
        "strategy": "trend_momentum",
        "opened_at": "2026-07-27T10:00:00Z",
    }]

    recent_trades = [{
        "ts": "2026-07-27T09:00:00Z",
        "symbol": "XAU/USD",
        "side": "buy",
        "price": 2350.00,
        "qty": 0.002,
        "pnl": 0.15,
        "pnl_pct": 3.0,
        "strategy": "trend_momentum",
        "exit_reason": "TP hit",
    }]

    regime = {"crypto": "BULL", "forex": "NEUTRAL", "gold": "BULL"}

    gates = {
        "confidence": True,
        "regime": True,
        "risk": True,
        "confluence": False,
        "dry_run": True,
        "sandbox": True,
    }

    strategies = {
        "trend_momentum":     {"signals": 12, "wins": 4, "losses": 2, "best_pf": 2.23, "best_pair": "XAU/USD"},
        "reversal_context":   {"signals": 3,  "wins": 1, "losses": 1, "best_pf": None, "best_pair": None},
        "volatility_breakout":{"signals": 2,  "wins": 0, "losses": 0, "best_pf": None, "best_pair": None},
    }

    reflection = {
        "last_nightly": "2026-07-27T02:00:00Z",
        "last_weekly":  "2026-07-21T03:00:00Z",
        "nightly_status": "completed",
        "weekly_status": "completed",
        "pending_suggestions": 2,
        "errors": [],
    }
    """
    # Læs eksisterende historik (append-only ringbuffer)
    history = _load_history()
    history.append({
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "value": portfolio.get("total_value", 0),
    })
    if len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": status,
        "portfolio": {**portfolio, "history": history},
        "positions": positions,
        "recent_trades": recent_trades[-50:],  # max 50
        "regime": regime,
        "gates": gates,
        "strategies": strategies,
        "reflection": reflection,
        "errors": errors or [],
    }

    # Skriv atomisk (temp-fil → rename)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=str, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def _load_history() -> list:
    """Indlæs eksisterende historik-punkter fra filen."""
    try:
        if STATUS_FILE.exists():
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            return data.get("portfolio", {}).get("history", [])
    except Exception:
        pass
    return []


# ─── EKSEMPEL: Brug i main.py ───────────────────────────────
#
# from status_writer import write_status
#
# def _write_dashboard_status(self):
#     """Kald dette fra engine-loopet hvert minut."""
#     open_positions = self.db.get_open_positions()
#     recent = self.db.get_recent_trades(limit=50)
#     portfolio_value = self.get_portfolio_value()
#
#     write_status(
#         mode="dry_run" if self.config.dry_run else "live",
#         status="running",
#         portfolio={
#             "total_value": portfolio_value,
#             "cash": self.get_cash(),
#             "buying_power": self.get_cash() * 4,   # 1x leverage → 4x (juster)
#             "open_pnl": sum(p.unrealized_pnl for p in open_positions),
#             "daily_pnl": self.daily_pnl,
#             "daily_pnl_pct": self.daily_pnl_pct,
#             "total_pnl": portfolio_value - 100.0,
#             "total_pnl_pct": (portfolio_value / 100.0 - 1) * 100,
#             "win_count": self.db.count_wins(),
#             "loss_count": self.db.count_losses(),
#             "profit_factor": self.db.get_profit_factor(),
#             "signals_today": self.signals_today,
#         },
#         positions=[p.to_dict() for p in open_positions],
#         recent_trades=[t.to_dict() for t in recent],
#         regime=self.regime_detector.current_regimes(),
#         gates={
#             "confidence": True,
#             "regime": self.config.regime_gate,
#             "risk": self.config.risk_gate,
#             "confluence": self.config.confluence_gate,
#             "dry_run": self.config.dry_run,
#             "sandbox": self.config.sandbox,
#         },
#         strategies=self.strategy_stats.to_dict(),
#         reflection=self.reflection_status(),
#     )
