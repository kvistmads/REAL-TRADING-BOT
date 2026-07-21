from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from core.database import Trade
from core.notifications import TelegramNotifier
from gates.base import GateResult
from strategies.base import Signal


def _config(enabled: bool) -> dict:
    return {"notifications": {"telegram": {"enabled": enabled, "daily_summary_time": "22:00"}}}


def _enabled_notifier(monkeypatch) -> TelegramNotifier:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    return TelegramNotifier(_config(True))


def _trade(**overrides) -> Trade:
    defaults = dict(
        id="t1", strategy_id="rsi_divergence", symbol="BTC/USDT", side="long",
        entry_price=45230.0, sl_price=40707.0, tp_price=54276.0, quantity=0.0001,
        stake_amount=5.0, pnl=1.23, pnl_pct=2.1,
        entry_time=datetime(2024, 1, 1, 10, 0), exit_time=datetime(2024, 1, 1, 14, 23),
        status="closed",
    )
    defaults.update(overrides)
    return Trade(**defaults)


class TestFormatting:
    @pytest.mark.asyncio
    async def test_trade_opened_format(self, monkeypatch):
        notifier = _enabled_notifier(monkeypatch)
        notifier._send = AsyncMock()
        await notifier.send_trade_opened(_trade(), confidence=0.74)
        text = notifier._send.call_args[0][0]
        assert "LONG BTC/USDT" in text
        assert "[rsi_divergence]" in text
        assert "Confidence: 0.74" in text
        assert "Stake: 5" in text

    @pytest.mark.asyncio
    async def test_trade_closed_format(self, monkeypatch):
        notifier = _enabled_notifier(monkeypatch)
        notifier._send = AsyncMock()
        await notifier.send_trade_closed(_trade(), reason="TP hit")
        text = notifier._send.call_args[0][0]
        assert "CLOSED BTC/USDT" in text
        assert "TP hit" in text
        assert "4h 23m" in text

    @pytest.mark.asyncio
    async def test_gate_rejected_format(self, monkeypatch):
        notifier = _enabled_notifier(monkeypatch)
        notifier._send = AsyncMock()
        signal = Signal("macd_volume", "ETH/USDT", "long", 0.6, "4h", {})
        result = GateResult("regime", False, 0.0, "Sideways market (ADX=18)")
        await notifier.send_gate_rejected(signal, result)
        text = notifier._send.call_args[0][0]
        assert "REJECTED ETH/USDT" in text
        assert "regime" in text
        assert "Sideways" in text

    @pytest.mark.asyncio
    async def test_daily_summary_format(self, monkeypatch):
        notifier = _enabled_notifier(monkeypatch)
        notifier._send = AsyncMock()
        stats = {
            "date": "2026-07-21", "total_trades": 3, "wins": 2, "losses": 1,
            "total_pnl": 2.41, "total_pnl_pct": 2.41,
            "best_strategy": ("rsi_divergence", 1.80),
            "worst_strategy": ("bollinger_squeeze", -0.38),
        }
        await notifier.send_daily_summary(stats)
        text = notifier._send.call_args[0][0]
        assert "Daily Summary" in text
        assert "Trades: 3" in text
        assert "rsi_divergence" in text


class TestDisabled:
    @pytest.mark.asyncio
    async def test_disabled_makes_no_http_call(self):
        notifier = TelegramNotifier(_config(False))
        assert notifier.enabled is False
        with patch("core.notifications.aiohttp.ClientSession") as session:
            await notifier.send_error("test")
            session.assert_not_called()

    def test_enabled_without_token_disables(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        notifier = TelegramNotifier(_config(True))
        assert notifier.enabled is False

    @pytest.mark.asyncio
    async def test_enabled_reaches_send(self, monkeypatch):
        notifier = _enabled_notifier(monkeypatch)
        notifier._send = AsyncMock()
        await notifier.send_error("boom")
        notifier._send.assert_called_once()
        assert "boom" in notifier._send.call_args[0][0]
