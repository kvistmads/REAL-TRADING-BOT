from __future__ import annotations

import logging

from gates.base import BaseGate, GateResult
from strategies.base import Signal

logger = logging.getLogger(__name__)


class RiskGate(BaseGate):
    name = "risk"
    blocking = True

    def __init__(self, config: dict):
        risk_cfg = config["gates"]["risk"]
        self.max_open_trades: int = config["trading"]["max_open_trades"]
        self.max_daily_loss_pct: float = risk_cfg["max_daily_loss_pct"]
        self.max_position_pct: float = risk_cfg["max_position_pct"]
        self.stake_amount: float = config["trading"]["stake_amount"]
        self.total_capital: float = config["trading"]["total_capital"]

    def evaluate(self, signal: Signal, context: dict) -> GateResult:
        open_count: int = context.get("open_trades_count", 0)
        daily_pnl: float = context.get("daily_pnl", 0.0)
        account_balance: float = context.get("account_balance", self.total_capital)

        checks = []

        # Tjek 1: Max åbne trades
        if open_count >= self.max_open_trades:
            reason = f"Max åbne trades nået: {open_count}/{self.max_open_trades}"
            logger.info(f"RiskGate AFVIST ({signal.symbol}): {reason}")
            return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)

        checks.append(f"åbne trades: {open_count}/{self.max_open_trades}")

        # Tjek 2: Dagligt tab
        max_loss = self.total_capital * self.max_daily_loss_pct / 100
        if daily_pnl <= -max_loss:
            reason = f"Daglig tab-grænse nået: {daily_pnl:.2f} USDT (limit: -{max_loss:.2f})"
            logger.info(f"RiskGate AFVIST ({signal.symbol}): {reason}")
            return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)

        checks.append(f"daglig PnL: {daily_pnl:.2f} USDT")

        # Tjek 3: Position size
        position_pct = (self.stake_amount / account_balance) * 100
        if position_pct > self.max_position_pct:
            reason = f"Position size for stor: {position_pct:.1f}% > {self.max_position_pct:.1f}%"
            logger.info(f"RiskGate AFVIST ({signal.symbol}): {reason}")
            return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)

        checks.append(f"position size: {position_pct:.1f}%")

        score = 1.0 - (open_count / self.max_open_trades) * 0.5
        return GateResult(
            gate_name=self.name,
            passed=True,
            score=round(score, 2),
            reason=f"Alle risk-tjek OK: {', '.join(checks)}",
        )
