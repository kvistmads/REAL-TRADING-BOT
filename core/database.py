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

from core.time_utils import utc_now

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
    # A/B-arm trade'en blev tildelt: "A" (kontrol) | "B" (kandidat) | None (intet
    # aktivt experiment). Udfyldes af execution/ab_router når et eksperiment kører.
    # create_all tilføjer kolonnen additivt — ingen migration nødvendig.
    ab_arm: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
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


class ShadowSignal(Base):
    """En nyhedsdrevet prognose — ikke et ægte trade, men en tracked forudsigelse.

    Loop C (News Intelligence) genererer disse fra headlines og evaluerer dem senere
    mod den faktiske prisbevægelse. De rører ALDRIG kapital — de er ren måling af, om
    news-signaler ville have haft merværdi (Phase 5 kan så aktivere et confirmation-hook).
    """

    __tablename__ = "shadow_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    symbol: Mapped[str] = mapped_column(String, nullable=False)  # "BTC/USDT", "EUR/USD" osv.
    predicted_direction: Mapped[str] = mapped_column(String, nullable=False)  # "up"|"down"|"neutral"
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0-1.0
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    eval_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # created_at + horizon
    # Referencepris ved signal-tidspunktet. Ikke i PRD-skemaet, men nødvendig for at
    # kunne beregne faktisk retning ved evaluering (vi kan ikke tidsrejse tilbage til
    # created_at-prisen bagefter). None = pris kunne ikke hentes → signalet kan ikke evalueres.
    price_at_signal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_direction: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # udfyldes ved eval
    correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # None = afventer eval
    news_summary: Mapped[str] = mapped_column(String, nullable=False, default="")
    sentiment_scores: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String, nullable=False, default="combined")
    # Konfirmation/diskrepans ift. tekniske strategier (JSON-lister af strategy_id).
    matching_strategies: Mapped[Any] = mapped_column(JSON, nullable=True)
    conflicting_strategies: Mapped[Any] = mapped_column(JSON, nullable=True)


class PromotionAlert(Base):
    """Log over sendte news-promotion-alerts (én pr. symbol×kilde) — undgår Telegram-spam."""

    __tablename__ = "news_promotion_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    n_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BacktestResult(Base):
    """Historisk backtest-baseline pr. (strategi × symbol) — importeret fra suite-kørsler.

    Research-laget (Phase 5) læser herfra for at sammenligne live-performance med den
    backtestede baseline. Tal gemmes normaliseret: win_rate/max_drawdown som fraktioner
    (0.0-1.0), total_return_pct i procent. profit_factor kan være None (ingen tabende
    trades → uendelig i metrics-laget; None her betyder "udefineret/inf").
    """

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String, nullable=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_sync_db() -> None:
    """Opret alle tabeller via den synkrone engine (bootstrap for reflection-loopsene).

    create_all er additivt for tabeller: eksisterende tabeller røres ikke, kun
    manglende oprettes — så en frisk DB (eller en ny tabel som backtest_results) er
    dækket her. NYE KOLONNER på eksisterende tabeller håndteres af Alembic
    (``alembic upgrade head``), ikke af denne funktion; se alembic/ og CLAUDE.md.
    """
    Base.metadata.create_all(sync_engine)
