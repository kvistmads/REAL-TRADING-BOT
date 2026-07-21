from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Trade, async_session_maker
from strategies.base import Signal

logger = logging.getLogger(__name__)


class PositionTracker:
    def __init__(self, config: dict):
        self.config = config
        self._open_positions: dict[str, Trade] = {}
        self._daily_pnl: float = 0.0
        self._daily_reset_date: str = datetime.utcnow().strftime("%Y-%m-%d")

    async def load_open_positions(self) -> None:
        from sqlalchemy import select
        async with async_session_maker() as session:
            result = await session.execute(
                select(Trade).where(Trade.status == "open")
            )
            for trade in result.scalars().all():
                self._open_positions[trade.id] = trade
        logger.info(f"Indlæst {len(self._open_positions)} åbne positioner fra DB")

    async def open_position(
        self,
        signal: Signal,
        sl_price: float,
        tp_price: float,
        order_result: dict,
        current_price: float,
        gate_scores: dict,
    ) -> Trade:
        stake = self.config["trading"]["stake_amount"]
        quantity = stake / current_price

        trade = Trade(
            id=str(uuid.uuid4()),
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=current_price,
            exit_price=None,
            sl_price=sl_price,
            tp_price=tp_price,
            quantity=quantity,
            stake_amount=stake,
            pnl=None,
            pnl_pct=None,
            entry_time=datetime.utcnow(),
            exit_time=None,
            status="open",
            gate_scores=gate_scores,
            market_regime=None,
            signal_data=signal.metadata,
            dry_run=self.config["trading"]["dry_run"],
        )

        async with async_session_maker() as session:
            session.add(trade)
            await session.commit()

        self._open_positions[trade.id] = trade
        logger.info(
            f"POSITION ÅBNET: {signal.side} {signal.symbol} @ {current_price:.4f} "
            f"SL={sl_price:.4f} TP={tp_price:.4f} [{signal.strategy_id}]"
        )
        return trade

    async def close_position(self, trade_id: str, exit_price: float, reason: str) -> Trade:
        trade = self._open_positions.get(trade_id)
        if trade is None:
            raise KeyError(f"Position ikke fundet: {trade_id}")

        if trade.side == "long":
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - exit_price) * trade.quantity

        pnl_pct = (pnl / trade.stake_amount) * 100

        trade.exit_price = exit_price
        trade.exit_time = datetime.utcnow()
        trade.status = "closed"
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round(pnl_pct, 2)

        async with async_session_maker() as session:
            db_trade = await session.get(Trade, trade_id)
            if db_trade:
                db_trade.exit_price = trade.exit_price
                db_trade.exit_time = trade.exit_time
                db_trade.status = trade.status
                db_trade.pnl = trade.pnl
                db_trade.pnl_pct = trade.pnl_pct
                await session.commit()

        self._daily_pnl += pnl
        del self._open_positions[trade_id]

        logger.info(
            f"POSITION LUKKET ({reason}): {trade.side} {trade.symbol} "
            f"entry={trade.entry_price:.4f} exit={exit_price:.4f} "
            f"PnL={pnl:.2f} USDT ({pnl_pct:.1f}%)"
        )
        return trade

    async def check_sl_tp(self, current_prices: dict[str, float]) -> list[Trade]:
        to_close: list[tuple[str, float, str]] = []

        for trade_id, trade in list(self._open_positions.items()):
            price = current_prices.get(trade.symbol)
            if price is None:
                continue

            if trade.side == "long":
                if price <= trade.sl_price:
                    to_close.append((trade_id, price, "stop_loss"))
                elif price >= trade.tp_price:
                    to_close.append((trade_id, price, "take_profit"))
            else:
                if price >= trade.sl_price:
                    to_close.append((trade_id, price, "stop_loss"))
                elif price <= trade.tp_price:
                    to_close.append((trade_id, price, "take_profit"))

        closed = []
        for trade_id, price, reason in to_close:
            closed.append(await self.close_position(trade_id, price, reason))
        return closed

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_pnl = 0.0
            self._daily_reset_date = today

    def get_open_count(self) -> int:
        return len(self._open_positions)

    def get_daily_pnl(self) -> float:
        self._reset_daily_if_needed()
        return self._daily_pnl

    def get_open_by_symbol(self, symbol: str) -> list[Trade]:
        return [t for t in self._open_positions.values() if t.symbol == symbol]
