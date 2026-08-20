"""Nedlukning på SIGTERM/SIGINT.

Botten køres fra LaunchAgent/cron, hvor `kill` sender SIGTERM. Uden en handler
dør processen på stedet og ccxt-sessionen lukkes aldrig. Testene her dækker den
sti — inklusive at SIGTERM kan være ARVET som SIG_IGN fra en non-interaktiv shell.
"""
import asyncio
import os
import signal

import pytest

from main import _install_signal_handlers, _request_shutdown


class _RestoreSignals:
    """Sæt handlers tilbage, så en test aldrig efterlader pytest med vores handler."""

    def __enter__(self):
        self._original = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        return self

    def __exit__(self, *exc):
        loop = asyncio.get_event_loop()
        for sig, handler in self._original.items():
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
            signal.signal(sig, handler)
        return False


class TestRequestShutdown:
    @pytest.mark.asyncio
    async def test_aflyser_en_koerende_task(self):
        task = asyncio.ensure_future(asyncio.sleep(3600))
        _request_shutdown(task, signal.SIGTERM)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_roerer_ikke_en_faerdig_task(self):
        task = asyncio.ensure_future(asyncio.sleep(0))
        await task
        _request_shutdown(task, signal.SIGTERM)  # må ikke kaste
        assert not task.cancelled()


class TestSignalHandlers:
    @pytest.mark.asyncio
    async def test_sigterm_aflyser_tasken_selv_naar_signalet_er_arvet_som_ign(self):
        """Kernescenariet: cron/non-interaktiv shell har sat SIGTERM til SIG_IGN."""
        with _RestoreSignals():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)  # simulér arven
            task = asyncio.ensure_future(asyncio.sleep(3600))
            _install_signal_handlers(task)

            os.kill(os.getpid(), signal.SIGTERM)

            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_sigint_aflyser_ogsaa_tasken(self):
        with _RestoreSignals():
            task = asyncio.ensure_future(asyncio.sleep(3600))
            _install_signal_handlers(task)

            os.kill(os.getpid(), signal.SIGINT)

            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)


class TestMainKoererStopVedSigterm:
    @pytest.mark.asyncio
    async def test_engine_stop_kaldes_naar_sigterm_rammer(self, monkeypatch):
        """Hele kæden: SIGTERM → engine-task aflyst → finally → engine.stop()."""
        import main as main_mod

        calls: list[str] = []

        class FakeEngine:
            def __init__(self, config):
                calls.append("init")

            async def start(self):
                calls.append("start")
                await asyncio.sleep(3600)

            async def stop(self):
                calls.append("stop")

        monkeypatch.setattr(main_mod, "TradingEngine", FakeEngine)
        monkeypatch.setattr(main_mod, "_setup_scheduler", lambda config: None)
        monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)

        with _RestoreSignals():
            main_task = asyncio.ensure_future(main_mod.main())
            # Lad main() nå at starte engine-tasken og installere handlers.
            while "start" not in calls:
                await asyncio.sleep(0.01)

            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(main_task, timeout=5)

        assert calls == ["init", "start", "stop"]
