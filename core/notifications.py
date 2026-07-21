from __future__ import annotations

import logging
import os

import aiohttp

from core.database import Trade
from gates.base import GateResult
from strategies.base import Signal

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _fmt(value: float, digits: int = 4) -> str:
    """Formatér pris uden unødvendige nuller (45230.0 → 45230, 1.1025 → 1.1025)."""
    if value is None:
        return "n/a"
    s = f"{value:,.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


class TelegramNotifier:
    def __init__(self, config: dict):
        tg_cfg = config.get("notifications", {}).get("telegram", {})
        self.enabled: bool = tg_cfg.get("enabled", False)
        self.token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID")

        if self.enabled and (not self.token or not self.chat_id):
            logger.warning(
                "Telegram enabled men TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID mangler i miljøet "
                "— notifikationer deaktiveres"
            )
            self.enabled = False

    async def _send(self, text: str) -> None:
        """Sender en besked til Telegram. No-op hvis deaktiveret. Kaster aldrig videre."""
        if not self.enabled:
            return
        url = _TELEGRAM_API.format(token=self.token)
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"Telegram-fejl ({resp.status}): {body}")
        except Exception as e:  # netværksfejl må ikke crashe botten
            logger.warning(f"Kunne ikke sende Telegram-besked: {e}")

    async def send_trade_opened(self, trade: Trade, confidence: float | None = None) -> None:
        emoji = "🟢" if trade.side == "long" else "🔴"
        conf = f"{confidence:.2f}" if confidence is not None else "n/a"
        text = (
            f"{emoji} {trade.side.upper()} {trade.symbol} [{trade.strategy_id}]\n"
            f"Entry: {_fmt(trade.entry_price)} | SL: {_fmt(trade.sl_price)} | TP: {_fmt(trade.tp_price)}\n"
            f"Confidence: {conf} | Stake: {_fmt(trade.stake_amount, 2)} USDT"
        )
        await self._send(text)

    async def send_trade_closed(self, trade: Trade, reason: str = "") -> None:
        pnl = trade.pnl or 0.0
        pnl_pct = trade.pnl_pct or 0.0
        sign = "+" if pnl >= 0 else ""
        duration = self._duration(trade)
        text = (
            f"🔵 CLOSED {trade.symbol} [{trade.strategy_id}]\n"
            f"P&L: {sign}{_fmt(pnl, 2)} ({sign}{pnl_pct:.1f}%) | Reason: {reason}\n"
            f"Duration: {duration}"
        )
        await self._send(text)

    async def send_gate_rejected(self, signal: Signal, result: GateResult) -> None:
        text = (
            f"⚠️ REJECTED {signal.symbol} [{signal.strategy_id}]\n"
            f"Gate: {result.gate_name} | Reason: {result.reason}"
        )
        await self._send(text)

    async def send_daily_summary(self, stats: dict) -> None:
        best = stats.get("best_strategy")
        worst = stats.get("worst_strategy")
        pnl = stats.get("total_pnl", 0.0)
        pnl_pct = stats.get("total_pnl_pct", 0.0)
        sign = "+" if pnl >= 0 else ""
        lines = [
            f"📊 Daily Summary — {stats.get('date', '')}",
            f"Trades: {stats.get('total_trades', 0)} | "
            f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}",
            f"P&L: {sign}{_fmt(pnl, 2)} ({sign}{pnl_pct:.2f}%)",
        ]
        if best:
            lines.append(f"Best: {best[0]} {'+' if best[1] >= 0 else ''}{_fmt(best[1], 2)}")
        if worst:
            lines.append(f"Worst: {worst[0]} {'+' if worst[1] >= 0 else ''}{_fmt(worst[1], 2)}")
        await self._send("\n".join(lines))

    async def send_error(self, message: str) -> None:
        await self._send(f"🚨 BOT ERROR — {message}")

    @staticmethod
    def _duration(trade: Trade) -> str:
        if not trade.entry_time or not trade.exit_time:
            return "n/a"
        delta = trade.exit_time - trade.entry_time
        total_minutes = int(delta.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes}m"
