from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import StrategyPerformance, Trade
from core.time_utils import utc_now

logger = logging.getLogger(__name__)


class PerformanceTracker:
    async def record_daily_snapshot(self, db_session: AsyncSession, on: date | None = None) -> None:
        """
        Kør dagligt (kl. 22:00). For hver strategi: beregn win_rate, avg_pnl,
        total_pnl, total_trades fra dagens lukkede trades → gem til strategy_performance.
        """
        on = on or utc_now().date()
        start = datetime(on.year, on.month, on.day)
        end = start + timedelta(days=1)

        result = await db_session.execute(
            select(Trade).where(
                Trade.status == "closed",
                Trade.exit_time >= start,
                Trade.exit_time < end,
            )
        )
        trades = result.scalars().all()

        by_strategy: dict[str, list[Trade]] = defaultdict(list)
        for t in trades:
            by_strategy[t.strategy_id].append(t)

        for strategy_id, strat_trades in by_strategy.items():
            pnls = [t.pnl or 0.0 for t in strat_trades]
            wins = sum(1 for p in pnls if p > 0)
            losses = sum(1 for p in pnls if p <= 0)
            total = len(strat_trades)
            snapshot = StrategyPerformance(
                id=str(uuid.uuid4()),
                strategy_id=strategy_id,
                snapshot_date=on,
                total_signals=0,
                total_trades=total,
                winning_trades=wins,
                losing_trades=losses,
                win_rate=round(wins / total, 4) if total else None,
                avg_pnl=round(sum(pnls) / total, 4) if total else None,
                total_pnl=round(sum(pnls), 4),
                max_drawdown=round(_max_drawdown(pnls), 4),
            )
            db_session.add(snapshot)

        await db_session.commit()
        logger.info(f"Performance-snapshot gemt for {len(by_strategy)} strategier ({on})")

    async def get_summary(self, db_session: AsyncSession, days: int = 7) -> dict:
        """Aggregeret summary for de seneste N dage — bruges til Telegram daily summary."""
        end = utc_now()
        start = end - timedelta(days=days)

        result = await db_session.execute(
            select(Trade).where(
                Trade.status == "closed",
                Trade.exit_time >= start,
            )
        )
        trades = result.scalars().all()

        pnls = [t.pnl or 0.0 for t in trades]
        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        staked = sum(t.stake_amount or 0.0 for t in trades)

        by_strategy: dict[str, float] = defaultdict(float)
        for t in trades:
            by_strategy[t.strategy_id] += t.pnl or 0.0

        best = max(by_strategy.items(), key=lambda kv: kv[1]) if by_strategy else None
        worst = min(by_strategy.items(), key=lambda kv: kv[1]) if by_strategy else None

        return {
            "date": end.strftime("%Y-%m-%d"),
            "days": days,
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 4),
            "total_pnl_pct": round(total_pnl / staked * 100, 2) if staked else 0.0,
            "best_strategy": best,
            "worst_strategy": worst,
        }


def _max_drawdown(pnls: list[float]) -> float:
    """Max peak-to-trough drawdown på den kumulative PnL-kurve (negativt tal)."""
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
    return max_dd
