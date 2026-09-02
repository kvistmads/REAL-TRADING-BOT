from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Trade, async_session_maker
from core.time_utils import utc_now
from strategies.base import Signal

logger = logging.getLogger(__name__)


def is_flip_breached(side: str, flip_level: float, close: float) -> bool:
    """Er strategiens præmis modbevist af denne bars BODY CLOSE?

    Flip level er ikke et stop loss: stoppet begrænser tabet, flip level er prisen
    hvor selve begrundelsen for handlen holder op med at gælde. Derfor bruges
    ``close`` og ikke ``low``/``high`` — et wick igennem er et sweep, ikke en
    invalidering (samme skelnen som i ``find_sr_levels``).
    """
    return close < flip_level if side == "long" else close > flip_level


def compute_breakeven_trigger(side: str, entry_price: float, tp_price: float,
                              pct: float) -> float | None:
    """Prisen hvor SL flyttes til entry: `pct` af vejen fra entry mod TP.

    Samme formel som backtest/runner._breakeven_trigger, så live og backtest
    flytter stoppet på samme sted. pct <= 0 → None (breakeven deaktiveret).
    """
    if not pct or pct <= 0:
        return None
    if side == "long":
        return entry_price + pct * (tp_price - entry_price)
    return entry_price - pct * (entry_price - tp_price)


class PositionTracker:
    def __init__(self, config: dict):
        self.config = config
        self._open_positions: dict[str, Trade] = {}
        self._daily_pnl: float = 0.0
        self._daily_reset_date: str = utc_now().strftime("%Y-%m-%d")
        # Hvilke trades der har fået SL flyttet til entry. Kun i memory — SL'en
        # selv persisteres i DB, så en genstart genopdager status via sl_price.
        self._breakeven_activated: dict[str, bool] = {}

    async def load_open_positions(self) -> None:
        from sqlalchemy import select
        async with async_session_maker() as session:
            result = await session.execute(
                select(Trade).where(Trade.status == "open")
            )
            for trade in result.scalars().all():
                self._open_positions[trade.id] = trade
                # SL == entry betyder at breakeven allerede blev aktiveret før
                # genstarten — genskab flaget så vi ikke logger aktiveringen igen.
                if trade.sl_price == trade.entry_price:
                    self._breakeven_activated[trade.id] = True
        logger.info(f"Indlæst {len(self._open_positions)} åbne positioner fra DB")

    async def open_position(
        self,
        signal: Signal,
        sl_price: float,
        tp_price: float,
        order_result: dict,
        current_price: float,
        gate_scores: dict,
        market_regime: str | None = None,
    ) -> Trade:
        stake = self.config["trading"]["stake_amount"]
        quantity = stake / current_price
        trigger_pct = self.config.get("trading", {}).get("breakeven_trigger_pct", 0.5)
        breakeven_trigger = compute_breakeven_trigger(
            signal.side, current_price, tp_price, trigger_pct
        )

        # Instrumentering (PRD del C): begge felter er denormaliseret ved entry og
        # IMMUTABLE — se Trade-docstringen. flip_level=None er et gyldigt udfald:
        # en strategi der ikke kan formulere hvad der ville modbevise den, er en
        # holdning frem for en strategi, og dét er værd at kunne tælle.
        flip_level = signal.metadata.get("flip_level") if signal.metadata else None
        if flip_level is None:
            logger.info(
                f"Intet flip level fra {signal.strategy_id} for {signal.symbol} "
                f"({signal.side}) — trade åbnes uden invaliderings-niveau"
            )

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
            entry_time=utc_now(),
            exit_time=None,
            status="open",
            gate_scores=gate_scores,
            market_regime=market_regime,
            signal_data=signal.metadata,
            dry_run=self.config["trading"]["dry_run"],
            breakeven_trigger=breakeven_trigger,
            confidence=signal.confidence,
            flip_level=float(flip_level) if flip_level is not None else None,
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
        trade.exit_time = utc_now()
        trade.status = "closed"
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round(pnl_pct, 2)
        # Flip level blev aldrig brudt mens handlen var åben → svaret på
        # "blev præmisen modbevist før exit?" er nu et endeligt Nej, ikke "endnu ikke".
        # Uden flip level forbliver feltet NULL: spørgsmålet giver ikke mening.
        if trade.flip_level is not None and trade.flip_breached_before_exit is None:
            trade.flip_breached_before_exit = False

        async with async_session_maker() as session:
            db_trade = await session.get(Trade, trade_id)
            if db_trade:
                db_trade.exit_price = trade.exit_price
                db_trade.exit_time = trade.exit_time
                db_trade.status = trade.status
                db_trade.pnl = trade.pnl
                db_trade.pnl_pct = trade.pnl_pct
                db_trade.flip_breached_before_exit = trade.flip_breached_before_exit
                await session.commit()

        self._daily_pnl += pnl
        del self._open_positions[trade_id]
        self._breakeven_activated.pop(trade_id, None)

        logger.info(
            f"POSITION LUKKET ({reason}): {trade.side} {trade.symbol} "
            f"entry={trade.entry_price:.4f} exit={exit_price:.4f} "
            f"PnL={pnl:.2f} USDT ({pnl_pct:.1f}%)"
        )
        return trade

    def is_breakeven_activated(self, trade_id: str) -> bool:
        return self._breakeven_activated.get(trade_id, False)

    async def activate_breakeven(self, trade_id: str, entry_price: float) -> None:
        """Flyt SL til entry-prisen (in-memory + DB) og marker trade'en."""
        trade = self._open_positions.get(trade_id)
        if trade is None:
            return
        trade.sl_price = entry_price
        self._breakeven_activated[trade_id] = True

        async with async_session_maker() as session:
            db_trade = await session.get(Trade, trade_id)
            if db_trade:
                db_trade.sl_price = entry_price
                await session.commit()

        logger.info(
            f"BREAKEVEN: {trade.side} {trade.symbol} — SL flyttet til entry "
            f"{entry_price:.4f} [{trade.strategy_id}]"
        )

    async def check_breakeven(self, current_prices: dict[str, float]) -> list[Trade]:
        """Aktivér breakeven på positioner der har nået deres trigger-pris.

        Køres FØR check_sl_tp, så en pris der både trigger breakeven og ligger
        under det oprindelige stop lukker i 0 frem for med tab.
        """
        activated: list[Trade] = []
        for trade_id, trade in list(self._open_positions.items()):
            if self.is_breakeven_activated(trade_id) or trade.breakeven_trigger is None:
                continue
            price = current_prices.get(trade.symbol)
            if price is None:
                continue
            hit = (
                price >= trade.breakeven_trigger if trade.side == "long"
                else price <= trade.breakeven_trigger
            )
            if hit:
                await self.activate_breakeven(trade_id, trade.entry_price)
                activated.append(trade)
        return activated

    async def check_time_stop(
        self, current_prices: dict[str, float], max_bars_held: int, bar_seconds: int
    ) -> list[Trade]:
        """Luk positioner der har været åbne >= max_bars_held barer.

        Holdetiden måles i vægur-tid siden entry omregnet til barer, ikke i antal
        faktiske barer — monitoren kender kun tiden, ikke OHLCV-serien. Samme
        grænse som backtestens time-stop (config: trading.max_bars_held).
        """
        if not max_bars_held or not bar_seconds:
            return []
        now = utc_now()
        to_close: list[tuple[str, float]] = []

        for trade_id, trade in list(self._open_positions.items()):
            price = current_prices.get(trade.symbol)
            if price is None or trade.entry_time is None:
                continue
            bars_held = (now - trade.entry_time).total_seconds() / bar_seconds
            if bars_held >= max_bars_held:
                to_close.append((trade_id, price))

        return [
            await self.close_position(trade_id, price, "time_stop")
            for trade_id, price in to_close
        ]

    async def check_flip_levels(
        self, closed_bars: dict[str, list[tuple[datetime, float]]]
    ) -> list[Trade]:
        """Registrér første body close gennem flip level. **OBSERVE-ONLY.**

        Lukker INGEN handel og rører ikke SL/TP — de eksisterende exits er uændrede.
        Formålet er at kunne skelne "stoppet var for stramt" (tesen holdt) fra "tesen
        var forkert" (flip brudt), som Loop A ikke kan se i dag.

        closed_bars: {symbol: [(bar_time, close), ...]} for barer der FAKTISK er lukket
        — engine'en filtrerer de endnu-uafsluttede fra, så et wick midt i en bar aldrig
        registreres som et brud. Kun barer der starter EFTER entry tæller.
        """
        breached: list[Trade] = []
        for trade_id, trade in list(self._open_positions.items()):
            if trade.flip_level is None or trade.flip_breached_at is not None:
                continue
            bars = closed_bars.get(trade.symbol)
            if not bars or trade.entry_time is None:
                continue
            hit = next(
                (
                    (bar_time, close)
                    for bar_time, close in bars
                    if bar_time > trade.entry_time
                    and is_flip_breached(trade.side, trade.flip_level, close)
                ),
                None,
            )
            if hit is None:
                continue
            bar_time, close = hit
            await self._mark_flip_breached(trade_id, bar_time)
            breached.append(trade)
            logger.info(
                f"FLIP LEVEL BRUDT (observation, handlen fortsætter): {trade.side} "
                f"{trade.symbol} close={close:.4f} gennem flip={trade.flip_level:.4f} "
                f"@ {bar_time} [{trade.strategy_id}]"
            )
        return breached

    async def _mark_flip_breached(self, trade_id: str, when: datetime) -> None:
        """Skriv brud-tidspunktet (in-memory + DB). flip_level selv røres ALDRIG."""
        trade = self._open_positions.get(trade_id)
        if trade is None:
            return
        trade.flip_breached_at = when
        trade.flip_breached_before_exit = True

        async with async_session_maker() as session:
            db_trade = await session.get(Trade, trade_id)
            if db_trade:
                db_trade.flip_breached_at = when
                db_trade.flip_breached_before_exit = True
                await session.commit()

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
        today = utc_now().strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_pnl = 0.0
            self._daily_reset_date = today

    def get_open_count(self) -> int:
        return len(self._open_positions)

    def get_open_positions(self) -> list[Trade]:
        return list(self._open_positions.values())

    def get_daily_pnl(self) -> float:
        self._reset_daily_if_needed()
        return self._daily_pnl

    def get_open_by_symbol(self, symbol: str) -> list[Trade]:
        return [t for t in self._open_positions.values() if t.symbol == symbol]
