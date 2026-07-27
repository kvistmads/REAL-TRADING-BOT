import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = "sqlite+aiosqlite:///trading_bot.db"
# Synkron URL til reflection-loopsene (Loop A/B). De kører som selvstændige
# cron-jobs og bruger blocking-klienter (Anthropic, ChromaDB), så en synkron
# session mod den samme SQLite-fil er både enklere og mere robust end at tvinge
# alt ind i event-loopet. Samme fil — kør aldrig samtidig med tung engine-skrivning.
SYNC_DATABASE_URL = "sqlite:///trading_bot.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
sync_session_maker = sessionmaker(bind=sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sl_price: Mapped[float] = mapped_column(Float, nullable=False)
    tp_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    stake_amount: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    gate_scores: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    market_regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    signal_data: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SignalLog(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    signal_metadata: Mapped[Any] = mapped_column("metadata", JSON, nullable=False, default=dict)
    sl_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trade_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class StrategyPerformance(Base):
    __tablename__ = "strategy_performance"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_date: Mapped[date] = mapped_column("date", Date, nullable=False)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Observation(Base):
    """En struktureret indsigt genereret af Loop A (nightly) eller Loop B (weekly)."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    loop: Mapped[str] = mapped_column(String, nullable=False)  # "nightly" | "weekly"
    observation_type: Mapped[str] = mapped_column(String, nullable=False)
    strategy_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parameter: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # current/suggested/evidence gemmes som native JSON (tal, dicts) — ikke JSON-strenge.
    current_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    suggested_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    auto_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # None = afventer brugerens svar; True = godkendt; False = afvist.
    approved_by_user: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    chromadb_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ABExperiment(Base):
    """Tracker et igangværende A/B-eksperiment på en parameter-ændring."""

    __tablename__ = "ab_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    parameter: Mapped[str] = mapped_column(String, nullable=False)
    value_a: Mapped[Any] = mapped_column(JSON, nullable=False)  # kontrol
    value_b: Mapped[Any] = mapped_column(JSON, nullable=False)  # kandidat
    trades_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_b: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_rate_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_factor_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_factor_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    min_trades_per_arm: Mapped[int] = mapped_column(Integer, nullable=False, default=30)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_sync_db() -> None:
    """Opret alle tabeller (inkl. observations/ab_experiments) via den synkrone engine.

    create_all er additivt: eksisterende tabeller røres ikke, kun manglende oprettes.
    Bruges af reflection-loopsene, som ikke deler event-loop med engine.
    """
    Base.metadata.create_all(sync_engine)
