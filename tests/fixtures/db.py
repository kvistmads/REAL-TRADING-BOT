"""
Isoleret test-DB til de lag der skriver til databasen (position_tracker m.fl.).

Produktionskoden importerer ``async_session_maker`` direkte fra core.database og
peger dermed på trading_bot.db. ``temp_db`` bygger en frisk SQLite-fil pr. test og
monkeypatcher session-makeren ind i de moduler der bruger den — så tests hverken
læser eller skriver produktionsdatabasen.
"""
from __future__ import annotations

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base


async def temp_db(monkeypatch, tmp_path, *modules: str):
    """Opret en tom test-DB og patch async_session_maker i `modules`.

    modules: modulstier hvis ``async_session_maker`` skal peges om,
    fx "execution.position_tracker". Returnerer session-makeren.
    """
    # NullPool: aiosqlite lukker sin worker-tråd når sessionen lukker. Uden den
    # overlever tråden pytest-asyncios event-loop og larmer med "Event loop is closed".
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db",
                                 poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    for module in modules:
        monkeypatch.setattr(f"{module}.async_session_maker", session_maker)
    return session_maker
