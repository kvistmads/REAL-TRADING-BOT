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

from core.database import ShadowSignal, Trade
from core.time_utils import utc_now

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


def extract_closed_trades(session, lookback_hours: int) -> pd.DataFrame:
    """Hent lukkede trades fra de seneste N TIMER med fuld kontekst som DataFrame."""
    cutoff = utc_now() - timedelta(hours=lookback_hours)
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
            # Instrumentering (PRD del C). confidence er signalets styrke ved entry —
            # ikke analystens tillid til et forslag. None på trades åbnet før
            # migrationen a3c1d9e4b217; de kan ikke genskabes bagudrettet.
            "confidence": t.confidence,
            "flip_level": t.flip_level,
            "flip_breached_at": t.flip_breached_at,
            "flip_breached_before_exit": t.flip_breached_before_exit,
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


def _outcome_stats(group: pd.DataFrame) -> pd.Series:
    """n / win_rate / avg_pnl_pct / profit_factor for én gruppe trades."""
    wins = group.loc[group["pnl_pct"] > 0, "pnl_pct"].sum()
    losses = -group.loc[group["pnl_pct"] < 0, "pnl_pct"].sum()
    if losses == 0:
        pf = float("inf") if wins > 0 else 0.0
    else:
        pf = round(wins / losses, 2)
    return pd.Series(
        {
            "n": len(group),
            "win_rate": round(group["won"].mean(), 3),
            "avg_pnl_pct": round(group["pnl_pct"].mean(), 3),
            "profit_factor": pf,
        }
    )


def aggregate_by_confidence_quartile(df: pd.DataFrame, q: int = 4) -> pd.DataFrame:
    """Win_rate og avg_pnl_pct pr. confidence-kvartil — den dimension Loop A manglede.

    Lagt VED SIDEN AF ``aggregate_by_symbol_session_regime``, ikke ind i den: de svarer
    på to forskellige spørgsmål, og den eksisterende gruppering skal ikke ændre form.

    Kvartiler frem for faste tærskler, fordi fordelingen af confidence er ukendt og
    strategiafhængig (trend_momentum har gulv 0.35, volatility_breakout 0.40). Med for
    få eller for ens værdier til `q` grupper falder ``pd.qcut`` tilbage på færre bånd.
    Trades uden confidence (åbnet før instrumenteringen) udelades — de har ingen
    kvartil at høre til.

    Kaldes pr. strategi: formlerne er forskellige, så deres bånd er ikke sammenlignelige.
    """
    if df.empty or "confidence" not in df.columns:
        return pd.DataFrame()
    d = df[df["confidence"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    try:
        d["confidence_band"] = pd.qcut(d["confidence"], q=q, duplicates="drop")
    except ValueError:  # for få unikke værdier til overhovedet at danne bånd
        return pd.DataFrame()

    out = (
        d.groupby("confidence_band", observed=True)
        .apply(_outcome_stats, include_groups=False)
        .reset_index()
    )
    out["confidence_band"] = out["confidence_band"].astype(str)
    return out


def aggregate_by_flip_breach(df: pd.DataFrame) -> pd.DataFrame:
    """Win_rate og avg_pnl_pct splittet på om flip level blev brudt før exit.

    Det er dét split der skiller to modsatrettede rettelser fra hinanden:
    brudt → tesen var forkert (justér signalet); ikke brudt, men tabt → tesen holdt
    og stoppet var for stramt (justér stop/entry). Uden splittet ser Loop A kun
    "strategien taber" og kan ikke vide hvilken vej den skal rette.

    ``flip_breached_before_exit`` er NULL for trades uden flip level; de vises som
    gruppen "no_flip_level" frem for at blive tavst udeladt — antallet af handler
    UDEN et invaliderings-niveau er i sig selv et resultat.
    """
    if df.empty or "flip_breached_before_exit" not in df.columns:
        return pd.DataFrame()
    d = df.copy()
    d["flip_group"] = (
        d["flip_breached_before_exit"]
        .map({True: "breached", False: "intact"})
        .fillna("no_flip_level")
    )
    return (
        d.groupby("flip_group", observed=True)
        .apply(_outcome_stats, include_groups=False)
        .reset_index()
    )


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


def extract_shadow_signal_performance(session, lookback_hours: int) -> pd.DataFrame:
    """Hent evaluerede ShadowSignals (Loop C) fra de seneste N TIMER.

    Samme rolle som ``extract_closed_trades`` men for news-signaler: outcome er
    ``correct`` (True/False) frem for pnl_pct. Bruges af Loop A Lag 3 til at
    korrelere news-signal-accuracy med strategiernes performance i samme perioder.
    Kun signaler der er blevet evalueret (correct != None) tages med.
    """
    cutoff = utc_now() - timedelta(hours=lookback_hours)
    signals = (
        session.execute(
            select(ShadowSignal).where(
                ShadowSignal.correct.isnot(None),
                ShadowSignal.created_at >= cutoff,
            )
        )
        .scalars()
        .all()
    )
    rows = [
        {
            "created_at": s.created_at,
            "symbol": s.symbol,
            "source": s.source,
            "predicted_direction": s.predicted_direction,
            "actual_direction": s.actual_direction,
            "confidence": s.confidence,
            "correct": bool(s.correct),
        }
        for s in signals
    ]
    return pd.DataFrame(rows)
