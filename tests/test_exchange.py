"""
Tests for core/exchange.py (Ændring 6).

Vigtigste kontrakt: i dry_run må INTET nå børsen. Derudover skal en afvist ordre
eller en netværksfejl boble op som en exception kalderen kan håndtere — den må
aldrig se ud som en gennemført ordre. ccxt mockes; ingen netværk i testene.
"""
from __future__ import annotations

import ccxt.async_support as ccxt
import pytest

from core.exchange import ExchangeClient
from strategies.base import Signal

DRY_RUN_CONFIG = {
    "trading": {"dry_run": True},
    "exchange": {"name": "binance", "sandbox": True},
}
LIVE_CONFIG = {
    "trading": {"dry_run": False},
    "exchange": {"name": "binance", "sandbox": True},
}


class FakeCcxt:
    """Registrerer ethvert kald, så et utilsigtet API-kald i dry-run fanges."""

    def __init__(self, result: dict | None = None, exc: Exception | None = None):
        self.result = result or {"id": "12345", "status": "closed"}
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    async def create_order(self, **kwargs):
        self.calls.append(("create_order", kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result

    async def fetch_balance(self):
        self.calls.append(("fetch_balance", {}))
        return {"USDT": {"free": 4200.0, "total": 4200.0}}

    async def fetch_positions(self):
        self.calls.append(("fetch_positions", {}))
        return [{"symbol": "BTC/USDT"}]

    async def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel_order", {"id": order_id, "symbol": symbol}))
        return {"id": order_id, "status": "canceled"}

    async def close(self):
        self.calls.append(("close", {}))


def _client(config: dict, fake: FakeCcxt) -> ExchangeClient:
    client = ExchangeClient(config)
    client.exchange = fake
    return client


def _signal(side: str = "long") -> Signal:
    return Signal("trend_momentum", "BTC/USDT", side, 0.72, "4h", {})


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_place_order_success(self):
        fake = FakeCcxt(result={"id": "abc", "status": "closed", "amount": 0.001})
        client = _client(LIVE_CONFIG, fake)

        order = await client.place_order(_signal(), 0.001, 45000.0, 60000.0)

        assert order["id"] == "abc"
        assert len(fake.calls) == 1
        name, kwargs = fake.calls[0]
        assert name == "create_order"
        assert kwargs["symbol"] == "BTC/USDT"
        assert kwargs["side"] == "buy"
        assert kwargs["type"] == "market"
        assert kwargs["amount"] == 0.001
        assert kwargs["params"] == {"stopLoss": 45000.0, "takeProfit": 60000.0}

    @pytest.mark.asyncio
    async def test_short_bliver_til_sell(self):
        fake = FakeCcxt()
        await _client(LIVE_CONFIG, fake).place_order(_signal("short"), 0.001, 60000.0, 45000.0)
        assert fake.calls[0][1]["side"] == "sell"

    @pytest.mark.asyncio
    async def test_place_order_rejected(self):
        """Børsen afviser (fx for lille ordre) → exception, ingen falsk kvittering."""
        fake = FakeCcxt(exc=ccxt.InvalidOrder("Filter failure: MIN_NOTIONAL"))
        client = _client(LIVE_CONFIG, fake)

        with pytest.raises(ccxt.InvalidOrder, match="MIN_NOTIONAL"):
            await client.place_order(_signal(), 0.0000001, 45000.0, 60000.0)

    @pytest.mark.asyncio
    async def test_place_order_insufficient_funds(self):
        fake = FakeCcxt(exc=ccxt.InsufficientFunds("balance too low"))
        with pytest.raises(ccxt.InsufficientFunds):
            await _client(LIVE_CONFIG, fake).place_order(_signal(), 1.0, 45000.0, 60000.0)

    @pytest.mark.asyncio
    async def test_place_order_timeout(self):
        fake = FakeCcxt(exc=ccxt.NetworkError("Request timed out"))
        client = _client(LIVE_CONFIG, fake)

        with pytest.raises(ccxt.NetworkError, match="timed out"):
            await client.place_order(_signal(), 0.001, 45000.0, 60000.0)


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_never_calls_api(self):
        fake = FakeCcxt()
        client = _client(DRY_RUN_CONFIG, fake)

        await client.place_order(_signal(), 0.001, 45000.0, 60000.0)
        await client.fetch_balance()
        await client.fetch_positions()
        await client.cancel_order("o1", "BTC/USDT")

        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_dry_run_returnerer_simuleret_ordre(self):
        client = _client(DRY_RUN_CONFIG, FakeCcxt())

        order = await client.place_order(_signal(), 0.001, 45000.0, 60000.0)

        assert order["dry_run"] is True
        assert order["symbol"] == "BTC/USDT"
        assert order["side"] == "buy"
        assert order["amount"] == 0.001
        assert order["sl_price"] == 45000.0
        assert order["tp_price"] == 60000.0
        assert order["id"]  # unikt id så trade'en kan spores

    @pytest.mark.asyncio
    async def test_dry_run_ordrer_har_unikke_ider(self):
        client = _client(DRY_RUN_CONFIG, FakeCcxt())
        first = await client.place_order(_signal(), 0.001, 45000.0, 60000.0)
        second = await client.place_order(_signal(), 0.001, 45000.0, 60000.0)
        assert first["id"] != second["id"]

    @pytest.mark.asyncio
    async def test_dry_run_balance_er_syntetisk(self):
        client = _client(DRY_RUN_CONFIG, FakeCcxt())
        assert (await client.fetch_balance())["USDT"]["free"] == 100.0

    @pytest.mark.asyncio
    async def test_dry_run_har_ingen_aabne_boers_positioner(self):
        assert await _client(DRY_RUN_CONFIG, FakeCcxt()).fetch_positions() == []

    @pytest.mark.asyncio
    async def test_dry_run_flag_kommer_fra_config(self):
        assert _client(DRY_RUN_CONFIG, FakeCcxt()).dry_run is True
        assert _client(LIVE_CONFIG, FakeCcxt()).dry_run is False


class TestLiveKald:
    @pytest.mark.asyncio
    async def test_balance_hentes_fra_boersen(self):
        fake = FakeCcxt()
        balance = await _client(LIVE_CONFIG, fake).fetch_balance()
        assert balance["USDT"]["free"] == 4200.0
        assert fake.calls[0][0] == "fetch_balance"

    @pytest.mark.asyncio
    async def test_cancel_order_sendes_videre(self):
        fake = FakeCcxt()
        await _client(LIVE_CONFIG, fake).cancel_order("o1", "BTC/USDT")
        assert fake.calls == [("cancel_order", {"id": "o1", "symbol": "BTC/USDT"})]

    @pytest.mark.asyncio
    async def test_close_lukker_forbindelsen(self):
        fake = FakeCcxt()
        await _client(LIVE_CONFIG, fake).close()
        assert fake.calls == [("close", {})]
