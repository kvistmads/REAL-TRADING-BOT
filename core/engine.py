from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from analytics.performance import PerformanceTracker
from core.database import (
    ShadowSignal,
    SignalLog,
    Trade,
    async_session_maker,
    init_db,
    sync_session_maker,
)
from core.exchange import ExchangeClient
from core.notifications import TelegramNotifier
from data.fetcher import DataFetcher
from data.indicators import add_all
from data.mt5_fetcher import MT5Fetcher
from execution.ab_router import get_assignment, record_trade_arm
from execution.position_tracker import PositionTracker
from reflection.news.accuracy_tracker import get_accuracy_report
from reflection.news.confirmation import apply_news_confirmation
from status_writer import write_status
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

# Dashboard-status skrives højst så ofte (sekunder) — throttle mod disk-spam.
_STATUS_INTERVAL = 60


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
        # Dashboard-status (Phase 5 Del B): tælleren nulstilles ved døgnskift, og status
        # skrives højst hvert _STATUS_INTERVAL sekund via en monotonisk throttle.
        self.signals_today = 0
        self._signals_today_date = datetime.utcnow().date()
        self._last_status_write = 0.0
        self._last_regimes: dict[str, str] = {}
        self._regime_gate: RegimeGate | None = None
        self._status_path = self.config.get("dashboard", {}).get("status_path", "bot_status.json")

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
            self._regime_gate = RegimeGate(self.config)
            self.gates.append(self._regime_gate)
        logger.info(f"Gates aktive: {[g.name for g in self.gates]}")

        # Skriv en initial status med det samme, så dashboardet viser live data ved opstart.
        await self._write_dashboard_status({})

    async def _tick(self) -> None:
        primary_tf = self.config["timeframes"]["primary"]
        symbols = self.config["symbols"]
        self._reset_signals_if_needed()

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

            # Klassificér regime pr. symbol til dashboardet (best-effort).
            if self._regime_gate is not None:
                try:
                    self._last_regimes[symbol] = self._regime_gate.classify(df)
                except Exception:
                    pass

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

                # News confirmation-hook (Phase 5 Del C): justér confidence ud fra
                # news intelligence. No-op når confirmation_hook.enabled=false (default).
                signal = self._apply_news_confirmation(signal, symbol)

                if signal.confidence < self.config["strategies"]["min_confidence"]:
                    continue

                self.signals_today += 1

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
        await self._maybe_write_status(current_prices)

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

    def _apply_news_confirmation(self, signal: Signal | None, symbol: str) -> Signal | None:
        """Justér signal-confidence via news intelligence (Phase 5 Del C).

        Tynd wrapper: læser confirmation_hook-config, henter shadow-signal-data via en
        synkron session og delegerer til den rene ``apply_news_confirmation``. Aktiveres
        KUN når ``confirmation_hook.enabled=true`` i config; best-effort (fejl → uændret).
        """
        hook = (
            self.config.get("reflection", {})
            .get("news_intelligence", {})
            .get("confirmation_hook", {})
        )
        if not hook.get("enabled", False) or signal is None:
            return signal
        try:
            with sync_session_maker() as session:
                return apply_news_confirmation(
                    session,
                    signal,
                    symbol,
                    enabled=True,
                    boost=hook.get("confidence_boost", 0.05),
                    damp=hook.get("confidence_damp", 0.08),
                )
        except Exception as e:  # hooket må aldrig vælte et tick
            logger.warning("News confirmation-hook fejlede for %s: %s", symbol, e)
            return signal

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

    # ------------------------------------------------------------------
    # Dashboard-status (Phase 5 Del B)
    # ------------------------------------------------------------------

    def _reset_signals_if_needed(self) -> None:
        today = datetime.utcnow().date()
        if today != self._signals_today_date:
            self.signals_today = 0
            self._signals_today_date = today

    async def _maybe_write_status(self, current_prices: dict[str, float]) -> None:
        if time.monotonic() - self._last_status_write >= _STATUS_INTERVAL:
            await self._write_dashboard_status(current_prices)

    async def _write_dashboard_status(self, current_prices: dict[str, float]) -> None:
        """Saml bot-tilstand og skriv bot_status.json. Best-effort — fejl vælter ikke tick."""
        try:
            open_positions = (
                self.position_tracker.get_open_positions() if self.position_tracker else []
            )
            positions = [
                self._position_to_dict(p, current_prices.get(p.symbol)) for p in open_positions
            ]
            open_pnl = sum(p["unrealized_pnl"] for p in positions)

            stats, recent_trades, per_strategy = await self._closed_trade_stats()
            total_capital = float(self.config["trading"]["total_capital"])
            realized = stats["total_pnl"]
            total_value = total_capital + realized + open_pnl
            daily_pnl = self.position_tracker.get_daily_pnl() if self.position_tracker else 0.0

            portfolio = {
                "total_value": round(total_value, 2),
                "cash": round(total_capital + realized, 2),
                "open_pnl": round(open_pnl, 2),
                "daily_pnl": round(daily_pnl, 2),
                "total_pnl": round(realized + open_pnl, 2),
                "total_pnl_pct": round((total_value / total_capital - 1) * 100, 2) if total_capital else 0.0,
                "win_count": stats["wins"],
                "loss_count": stats["losses"],
                "profit_factor": stats["profit_factor"],
                "signals_today": self.signals_today,
                "open_positions": len(positions),
            }
            gates = {
                "confidence": True,
                "regime": bool(self.config["gates"].get("regime", {}).get("enabled")),
                "risk": bool(self.config["gates"].get("risk", {}).get("enabled")),
                "confluence": bool(self.config["gates"].get("confluence", {}).get("enabled")),
                "dry_run": bool(self.config["trading"].get("dry_run")),
                "sandbox": bool(self.config.get("exchange", {}).get("sandbox")),
            }
            mode = "dry_run" if self.config["trading"].get("dry_run") else "live"

            write_status(
                mode=mode,
                status="running",
                portfolio=portfolio,
                positions=positions,
                recent_trades=recent_trades,
                regime=dict(self._last_regimes),
                gates=gates,
                strategies=per_strategy,
                reflection=self._loop_c_status(),
                path=self._status_path,
            )
            self._last_status_write = time.monotonic()
        except Exception as e:
            logger.warning("Kunne ikke skrive dashboard-status: %s", e)

    async def _closed_trade_stats(self) -> tuple[dict, list[dict], dict]:
        """Aggreger lukkede trades: overordnede stats, seneste 50, og pr. strategi."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Trade).where(Trade.status == "closed").order_by(Trade.exit_time.desc())
            )
            closed = result.scalars().all()

        pnls = [t.pnl or 0.0 for t in closed]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p <= 0))
        # inf er ikke gyldig JSON → None når der ingen tabende trades er.
        pf = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

        per_strategy: dict[str, dict] = {}
        for t in closed:
            s = per_strategy.setdefault(
                t.strategy_id, {"trades": 0, "wins": 0, "total_pnl": 0.0}
            )
            s["trades"] += 1
            s["wins"] += 1 if (t.pnl or 0.0) > 0 else 0
            s["total_pnl"] = round(s["total_pnl"] + (t.pnl or 0.0), 4)
        for s in per_strategy.values():
            s["win_rate"] = round(s["wins"] / s["trades"], 3) if s["trades"] else 0.0

        stats = {
            "wins": wins,
            "losses": losses,
            "total_pnl": round(sum(pnls), 4),
            "profit_factor": pf,
            "total_trades": len(closed),
        }
        recent = [self._trade_to_dict(t) for t in closed[:50]]
        return stats, recent, per_strategy

    def _loop_c_status(self) -> dict:
        """Loop C (News Intelligence) status til dashboardet. Best-effort → tomme felter."""
        try:
            with sync_session_maker() as session:
                report = get_accuracy_report(session)
                latest = (
                    session.execute(
                        select(ShadowSignal).order_by(ShadowSignal.created_at.desc())
                    )
                    .scalars()
                    .first()
                )
                last_signal = None
                if latest is not None:
                    last_signal = {
                        "symbol": latest.symbol,
                        "direction": latest.predicted_direction,
                        "confidence": latest.confidence,
                        "ts": latest.created_at.isoformat() if latest.created_at else None,
                    }
            acc_by_symbol = {
                sym: v["accuracy"]
                for sym, v in report.get("by_symbol", {}).items()
                if v.get("total", 0) >= 10
            }
            return {
                "loop_c": {
                    "total_signals": report.get("total", 0),
                    "accuracy": report.get("accuracy", 0.0),
                    "accuracy_by_symbol": acc_by_symbol,
                    "last_signal": last_signal,
                }
            }
        except Exception as e:  # Loop C-tabeller findes måske ikke endnu
            logger.debug("Loop C status utilgængelig: %s", e)
            return {"loop_c": {"total_signals": 0, "accuracy_by_symbol": {}, "last_signal": None}}

    def _position_to_dict(self, trade: Trade, current_price: float | None) -> dict:
        price = float(current_price) if current_price is not None else float(trade.entry_price)
        if trade.side == "long":
            unreal = (price - trade.entry_price) * trade.quantity
        else:
            unreal = (trade.entry_price - price) * trade.quantity
        return {
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "strategy_id": trade.strategy_id,
            "entry_price": round(trade.entry_price, 6),
            "current_price": round(price, 6),
            "sl_price": round(trade.sl_price, 6),
            "tp_price": round(trade.tp_price, 6),
            "quantity": trade.quantity,
            "stake_amount": trade.stake_amount,
            "unrealized_pnl": round(unreal, 4),
            "unrealized_pnl_pct": round(unreal / trade.stake_amount * 100, 2) if trade.stake_amount else 0.0,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "market_regime": trade.market_regime,
        }

    @staticmethod
    def _trade_to_dict(t: Trade) -> dict:
        return {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "strategy_id": t.strategy_id,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "market_regime": t.market_regime,
            "ab_arm": t.ab_arm,
        }

    async def stop(self) -> None:
        self._running = False
        if self.fetcher:
            self.fetcher.shutdown()
        if self.exchange:
            await self.exchange.close()
