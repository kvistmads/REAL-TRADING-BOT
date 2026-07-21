from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from strategies.base import BaseStrategy


class StrategyRegistry:
    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> BaseStrategy:
        if name not in self._strategies:
            raise KeyError(f"Strategi ikke fundet: {name}")
        return self._strategies[name]

    def get_enabled(self, enabled_names: list[str]) -> list[BaseStrategy]:
        return [self._strategies[n] for n in enabled_names if n in self._strategies]

    def all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())


def load_strategies() -> StrategyRegistry:
    registry = StrategyRegistry()
    strategies_path = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(strategies_path)]):
        if module_name in ("base", "registry"):
            continue
        try:
            module = importlib.import_module(f"strategies.{module_name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseStrategy) and obj is not BaseStrategy and hasattr(obj, "name"):
                    instance = obj()
                    registry.register(instance)
        except Exception:
            pass

    return registry
