"""Læser backtestede baselines fra BacktestResult-tabellen til research-kontekst.

Erstatter den tidligere CSV-læsning: backtest/runner.py importerer nu suite-resultater
til DB (se ``save_results_to_db``), og research-laget slår op her. Alt er best-effort —
manglende data giver None, aldrig en exception.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select

from core.database import BacktestResult, sync_session_maker

logger = logging.getLogger(__name__)

# Under så få live-trades er en sammenligning med backtest ikke meningsfuld.
_MIN_LIVE_TRADES = 10
# Relativ margin før vi kalder en afvigelse for over-/underperformance.
_WR_MARGIN = 0.05


def get_backtest_baseline(strategy_id: str, symbol: str, session=None) -> Optional[dict]:
    """Returnér seneste backtest-baseline for (strategy_id × symbol), ellers None.

    session kan injiceres (tests); ellers bruges den synkrone produktions-session.
    """
    own_session = session is None
    if own_session:
        session = sync_session_maker()
    try:
        row = (
            session.execute(
                select(BacktestResult)
                .where(
                    BacktestResult.strategy_id == strategy_id,
                    BacktestResult.symbol == symbol,
                )
                .order_by(BacktestResult.run_at.desc())
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        period = None
        if row.period_start and row.period_end:
            period = f"{row.period_start.date()} to {row.period_end.date()}"
        return {
            "wr": row.win_rate,
            "pf": row.profit_factor,
            "sharpe": row.sharpe,
            "trades": row.total_trades,
            "max_dd": row.max_drawdown,
            "total_return_pct": row.total_return_pct,
            "period": period,
            "source": row.source_file,
        }
    except Exception as e:  # pragma: no cover - DB-miljøafhængigt
        logger.warning("Kunne ikke læse backtest-baseline for %s×%s: %s", strategy_id, symbol, e)
        return None
    finally:
        if own_session:
            session.close()


def compare_live_vs_backtest(live_metrics: dict, backtest_baseline: Optional[dict]) -> str:
    """Byg en kort sammenligning af live-performance mod backtest-baseline.

    Håndterer eksplicit: ingen baseline, for få live-trades, samt over-/underperformance
    på win-rate og profit-factor.
    """
    if not backtest_baseline:
        return "Ingen backtest-baseline for denne kombination — kan ikke sammenligne."

    live = live_metrics or {}
    n_live = int(live.get("trades", 0) or 0)
    src = backtest_baseline.get("source", "backtest")
    period = backtest_baseline.get("period") or "ukendt periode"
    header = f"Backtest-baseline ({src}, {period})"

    if n_live < _MIN_LIVE_TRADES:
        return (
            f"{header}: kun {n_live} live-trades — for få til en meningsfuld sammenligning "
            f"med backtest (baseline WR {_fmt_pct(backtest_baseline.get('wr'))}, "
            f"PF {_fmt_pf(backtest_baseline.get('pf'))})."
        )

    lines = [f"{header}:"]
    bt_wr = backtest_baseline.get("wr")
    live_wr = live.get("wr")
    if bt_wr is not None and live_wr is not None:
        diff = live_wr - bt_wr
        if diff < -_WR_MARGIN:
            verdict = f"UNDERPRÆSTERER ({live_wr:.0%} vs backtest {bt_wr:.0%}) — mulig overfit eller regime-skift"
        elif diff > _WR_MARGIN:
            verdict = f"OVERPRÆSTERER ({live_wr:.0%} vs backtest {bt_wr:.0%}) — parametrene arbejder"
        else:
            verdict = f"på niveau med backtest ({live_wr:.0%} vs {bt_wr:.0%})"
        lines.append(f"- Win-rate: {verdict}.")

    bt_pf = backtest_baseline.get("pf")
    live_pf = live.get("pf")
    if bt_pf is not None and live_pf is not None:
        if live_pf < bt_pf:
            lines.append(f"- Profit-factor lavere live ({live_pf:.2f} vs backtest {bt_pf:.2f}).")
        else:
            lines.append(f"- Profit-factor holder ({live_pf:.2f} vs backtest {bt_pf:.2f}).")

    return "\n".join(lines)


def _fmt_pct(v) -> str:
    return f"{v:.0%}" if isinstance(v, (int, float)) else "?"


def _fmt_pf(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "∞/?"
