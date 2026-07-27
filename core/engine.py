from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from analytics.performance import PerformanceTracker
from core.database import SignalLog, async_session_maker, init_db, sync_session_maker
from core.exchange import ExchangeClient
from core.notifications import TelegramNotifier
from data.fetcher import DataFetcher
from data.indicators import add_all
from data.mt5_fetcher import MT5Fetcher
from execution.ab_router import get_assignment, record_trade_arm
from execution.position_tracker import PositionTracker
from gates.base import GateResult
from gates.regime import RegimeGate
from gates.risk import RiskGate
from strategies.base import BaseStrategy, Signal
from strategies.registry import load_strategies

logger = logging.getLogger(__name__)

_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}


class TradingEngine:
    def __init__(self, config: dict):
        self.config = config
        self.exchange: ExchangeClient | None = None
        self.fetcher: DataFetcher | None = None
        self.position_tracker: PositionTracker | None = None
        self.notifier: TelegramNotifier | None = None
        self.performance = PerformanceTracker()
        self.strategies: list[BaseStrategy] = []
        self.gates: list = []
        self._running = False
        self._last_summary_date = None
        self._summary_hour = self._parse_summary_hour()

    def _parse_summary_hour(self) -> int:
        raw = self.config.get("notifications", {}).get("telegram", {}).get(
            "daily_summary_time", "22:00"
        )
        try:
            return int(str(raw).split(":")[0])
        except (ValueError, IndexError):
            return 22

    async def start(self) -> None:
        await self._initialize()
        self._running = True
        logger.info("TradingEngine startet — kører i dry-run" if self.config["trading"]["dry_run"] else "TradingEngine startet — LIVE MODE")
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Fejl i tick: {e}", exc_info=True)
            await asyncio.sleep(self._get_sleep_seconds())

    async def _initialize(self) -> None:
        await init_db()
        self.exchange = ExchangeClient(self.config)
        self.fetcher = DataFetcher(self.exchange, self.config)
        self.position_tracker = PositionTracker(self.config)
        self.notifier = TelegramNotifier(self.config)
        await self.position_tracker.load_open_positions()

        registry = load_strategies()
        enabled = self.config["strategies"]["enabled"]
        self.strategies = registry.get_enabled(enabled)
        logger.info(f"Strategier loadet: {[s.name for s in self.strategies]}")

        if self.config["gates"]["risk"]["enabled"]:
            self.gates.append(RiskGate(self.config))
        if self.config["gates"].get("regime", {}).get("enabled"):
            self.gates.append(RegimeGate(self.config))
        logger.info(f"Gates aktive: {[g.name for g in self.gates]}")

    async def _tick(self) -> None:
        primary_tf = self.config["timeframes"]["primary"]
        symbols = self.config["symbols"]

        # Hent aktuelle priser og tjek SL/TP
        current_prices: dict[str, float] = {}
        for symbol in symbols:
            try:
                if MT5Fetcher.is_forex(symbol):
                    price = self.fetcher.get_tick_price(symbol)
                    if price is not None:
                        current_prices[symbol] = price
                    continue
                ticker = await self.exchange.fetch_ticker(symbol)
                current_prices[symbol] = ticker["last"]
            except Exception as e:
                logger.warning(f"Kunne ikke hente pris for {symbol}: {e}")

        if current_prices:
            closed = await self.position_tracker.check_sl_tp(current_prices)
            for trade in closed:
                await self.notifier.send_trade_closed(trade, self._exit_reason(trade))
            if closed:
                logger.info(f"{len(closed)} positioner lukket via SL/TP")

        # Hent OHLCV for alle symboler
        all_bars = await self.fetcher.get_multi(symbols, primary_tf)

        for symbol, df in all_bars.items():
            if df is None or len(df) < 30:
                continue

            df = add_all(df)

            for strategy in self.strategies:
                # A/B: kør signal på arm-tildelte params hvis et eksperiment er aktivt,
                # ellers tom dict → strategiens defaults (assignment=None, ab_arm=None).
                assignment = get_assignment(strategy.name)
                params = assignment.params if assignment else {}
                try:
                    signal = strategy.generate_signal(df, symbol, params=params)
                except Exception as e:
                    logger.error(f"Fejl i {strategy.name} for {symbol}: {e}")
                    continue

                if signal is None:
                    continue

                if signal.confidence < self.config["strategies"]["min_confidence"]:
                    continue

                logger.info(
                    f"SIGNAL: {strategy.name} {signal.side} {symbol} "
                    f"confidence={signal.confidence:.2f}"
                )

                # Evaluer gates
                current_price = current_prices.get(symbol)
                if current_price is None:
                    continue

                context = {
                    "current_price": current_price,
                    "open_trades_count": self.position_tracker.get_open_count(),
                    "daily_pnl": self.position_tracker.get_daily_pnl(),
                    "account_balance": self.config["trading"]["total_capital"],
                    "asset_class": BaseStrategy.get_asset_class(symbol),
                    "df": df,
                    "config": self.config,
                }

                gate_scores: dict = {}
                gate_passed = True

                for gate in self.gates:
                    result: GateResult = gate.evaluate(signal, context)
                    gate_scores[gate.name] = {
                        "passed": result.passed,
                        "score": result.score,
                        "reason": result.reason,
                    }
                    if not result.passed and gate.blocking:
                        gate_passed = False
                        logger.info(f"Gate '{gate.name}' afviste signal: {result.reason}")
                        await self.notifier.send_gate_rejected(signal, result)
                        break

                await self._log_signal(signal, gate_passed, None)

                if not gate_passed:
                    continue

                # Beregn SL/TP og åbn position
                sl_price, tp_price = self._resolve_sl_tp(signal, current_price)

                order = await self.exchange.place_order(signal,
                    self.config["trading"]["stake_amount"] / current_price,
                    sl_price, tp_price)

                trade = await self.position_tracker.open_position(
                    signal, sl_price, tp_price, order, current_price, gate_scores,
                    market_regime=context.get("regime"),
                )

                # Tag trade'en med sin A/B-arm + øg eksperimentets tæller (synkron
                # session mod samme SQLite-fil; trade er allerede committet ovenfor).
                if assignment:
                    with sync_session_maker() as ab_session:
                        record_trade_arm(trade.id, assignment, ab_session)
                        ab_session.commit()

                await self.notifier.send_trade_opened(trade, signal.confidence)

        await self._maybe_daily_summary()

    async def _log_signal(self, signal: Signal, gate_passed: bool, trade_id: str | None) -> None:
        log = SignalLog(
            id=str(uuid.uuid4()),
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            side=signal.side,
            confidence=signal.confidence,
            timeframe=signal.timeframe,
            signal_metadata=signal.metadata,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            timestamp=datetime.utcnow(),
            gate_passed=gate_passed,
            trade_id=trade_id,
        )
        async with async_session_maker() as session:
            session.add(log)
            await session.commit()

    def _resolve_sl_tp(self, signal: Signal, current_price: float) -> tuple[float, float]:
        if signal.sl_price is not None and signal.tp_price is not None:
            return signal.sl_price, signal.tp_price

        asset_class = BaseStrategy.get_asset_class(signal.symbol)
        defaults = self.config["risk_defaults"][asset_class]
        sl_pct = defaults["sl_pct"] / 100
        tp_pct = defaults["tp_pct"] / 100

        if signal.side == "long":
            sl = current_price * (1 - sl_pct)
            tp = current_price * (1 + tp_pct)
        else:
            sl = current_price * (1 + sl_pct)
            tp = current_price * (1 - tp_pct)

        return sl, tp

    def _get_sleep_seconds(self) -> int:
        primary_tf = self.config["timeframes"]["primary"]
        return _TIMEFRAME_SECONDS.get(primary_tf, 14400)

    @staticmethod
    def _exit_reason(trade) -> str:
        """Udled om en lukket trade ramte TP eller SL ud fra exit-prisen."""
        if trade.exit_price is None:
            return "closed"
        tp_hit = (trade.side == "long" and trade.exit_price >= trade.tp_price) or (
            trade.side == "short" and trade.exit_price <= trade.tp_price
        )
        return "TP hit" if tp_hit else "SL hit"

    async def _maybe_daily_summary(self) -> None:
        now = datetime.now()
        if self._last_summary_date == now.date() or now.hour < self._summary_hour:
            return
        self._last_summary_date = now.date()
        await self.run_daily_summary()

    async def run_daily_summary(self) -> None:
        """Gem dagligt performance-snapshot og send Telegram-summary. Kan trigges manuelt til test."""
        try:
            async with async_session_maker() as session:
                await self.performance.record_daily_snapshot(session)
                stats = await self.performance.get_summary(session, days=1)
            await self.notifier.send_daily_summary(stats)
            logger.info("Daglig summary sendt")
        except Exception as e:
            logger.error(f"Fejl i daglig summary: {e}", exc_info=True)

    async def stop(self) -> None:
        self._running = False
        if self.fetcher:
            self.fetcher.shutdown()
        if self.exchange:
            await self.exchange.close()
