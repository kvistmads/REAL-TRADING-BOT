"""Trækker og beriger lukkede trades fra DB til analyse.

Tilpasset det faktiske Trade-schema (core/database.py):
- tidsstempler hedder entry_time / exit_time (ikke opened_at/closed_at)
- strategiens indikator-metadata ligger i signal_data (JSON-dict)
- gate_scores er {gate_name: {passed, score, reason}}; regime-labelen ligger
  desuden fladt i market_regime-kolonnen. ADX gemmes ikke struktureret, men kan
  ofte udtrækkes fra regime-gatens reason-tekst ("ADX=27").
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func, select

from core.database import Trade

_ADX_RE = re.compile(r"ADX\s*=\s*(\d+(?:\.\d+)?)")


def _as_dict(value: Any) -> dict:
    """gate_scores/signal_data kommer som dict via JSON-kolonnen, men tål også str."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _trading_session(dt: datetime) -> str:
    """Grov opdeling i handelssessioner efter UTC-time."""
    if dt is None:
        return "unknown"
    h = dt.hour
    if 0 <= h < 8:
        return "asian"
    if 8 <= h < 13:
        return "london"
    if 13 <= h < 21:
        return "ny"
    return "asian"  # 21-24 → tilbage i asian


def count_closed_trades(session) -> int:
    """Totalt antal lukkede trades i DB (bruges af confidence-gaten mod 200-grænsen)."""
    return session.execute(
        select(func.count()).select_from(Trade).where(Trade.status == "closed")
    ).scalar_one()


def extract_closed_trades(session, lookback_days: int) -> pd.DataFrame:
    """Hent lukkede trades fra de seneste N dage med fuld kontekst som DataFrame."""
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    trades = (
        session.execute(
            select(Trade).where(
                Trade.status == "closed",
                Trade.exit_time >= cutoff,
            )
        )
        .scalars()
        .all()
    )

    rows = []
    for t in trades:
        gate = _as_dict(t.gate_scores)
        meta = _as_dict(t.signal_data)
        regime = gate.get("regime", {}) if isinstance(gate.get("regime"), dict) else {}
        regime_reason = regime.get("reason", "") or ""
        adx_match = _ADX_RE.search(regime_reason)

        pnl_pct = t.pnl_pct if t.pnl_pct is not None else 0.0
        row = {
            "id": t.id,
            "strategy_id": t.strategy_id,
            "symbol": t.symbol,
            "side": t.side,
            "pnl": t.pnl,
            "pnl_pct": pnl_pct,
            "won": pnl_pct > 0,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "hour": t.entry_time.hour if t.entry_time else None,
            "weekday": t.entry_time.weekday() if t.entry_time else None,
            "session": _trading_session(t.entry_time),
            "market_regime": t.market_regime,
            "regime_score": regime.get("score"),
            "adx_at_entry": float(adx_match.group(1)) if adx_match else None,
            "atr_pct_at_entry": None,  # gemmes ikke struktureret i gate_scores i dag
        }
        # Flad signal_data ud som meta_* kolonner (rsi, ema_gap, cross_strength osv.)
        for k, v in meta.items():
            row[f"meta_{k}"] = v
        rows.append(row)

    return pd.DataFrame(rows)


def meta_columns(df: pd.DataFrame) -> list[str]:
    """Navnene på de udpakkede signal_data-felter (til Lag 1-prompten)."""
    return [c for c in df.columns if c.startswith("meta_")]


def aggregate_by_symbol_session_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot til Lag 2: win_rate, profit_factor og n pr. (symbol × session × regime)."""
    if df.empty:
        return pd.DataFrame()

    def _pf(group: pd.DataFrame) -> float:
        wins = group.loc[group["pnl_pct"] > 0, "pnl_pct"].sum()
        losses = -group.loc[group["pnl_pct"] < 0, "pnl_pct"].sum()
        if losses == 0:
            return float("inf") if wins > 0 else 0.0
        return round(wins / losses, 2)

    out = (
        df.groupby(["symbol", "session", "market_regime"], dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "win_rate": round(g["won"].mean(), 3),
                    "avg_pnl_pct": round(g["pnl_pct"].mean(), 3),
                    "profit_factor": _pf(g),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    return out


def weekly_pnl_by_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """Lag 3: ugentlig sum-pnl pr. strategi (rækker=uge, kolonner=strategi)."""
    if df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["week"] = pd.to_datetime(d["exit_time"]).dt.to_period("W").astype(str)
    pivot = d.pivot_table(
        index="week", columns="strategy_id", values="pnl_pct", aggfunc="sum", fill_value=0.0
    )
    return pivot


def strategy_correlation(weekly_pnl: pd.DataFrame) -> pd.DataFrame:
    """Pearson-korrelationsmatrix mellem strategiernes ugentlige pnl."""
    if weekly_pnl.empty or weekly_pnl.shape[1] < 2:
        return pd.DataFrame()
    return weekly_pnl.corr(method="pearson").round(2)
