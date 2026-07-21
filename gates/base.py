from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from strategies.base import Signal


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    score: float  # 0.0–1.0
    reason: str


class BaseGate(ABC):
    name: str
    blocking: bool = True  # True = afviser trade / False = advisory

    @abstractmethod
    def evaluate(self, signal: Signal, context: dict) -> GateResult:
        """
        context: current_price, open_trades_count, daily_pnl,
                 account_balance, asset_class, config
        """
