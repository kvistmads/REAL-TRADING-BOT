"""Loop B — Weekly Architecture Analysis (PRD Opgave 3).

Kører søndag 03:00 UTC eller manuelt. Samler en snapshot af kodebasen, beder LLM'en
om arkitektur-/performance-/pålideligheds-fund og skriver ALTID kun en rapport —
intet auto-applies fra denne loop (guardrail #6).

    .venv/bin/python reflection/weekly.py --dry-run
    .venv/bin/python reflection/weekly.py

Bemærk: profilering kører IKKE main.py (som er et uendeligt live-loop med netværk).
I stedet profileres den CPU-tunge, sideeffekt-frie hot path: indikator-beregning +
signal-generering på syntetisk data. I --dry-run springes profilering/coverage over
for at holde kørslen hurtig.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import logging
import os
import pstats
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Gør projekt-roden importerbar når scriptet køres direkte (python reflection/weekly.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflection.analyst import ReflectionAnalyst
from reflection.reporter import TelegramReporter, write_weekly_report
from reflection.research.researcher import Researcher

_STRATEGY_IDS = ["trend_momentum", "reversal_context", "volatility_breakout"]

logger = logging.getLogger(__name__)

# .claude rummer agent-worktrees: en fuld kopi af repoet, som ellers ville
# tælle hver modul med to gange og få kodebasen til at se duplikeret ud.
_SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "backtest_results", ".claude"}


# ---------------------------------------------------------------------------
# Snapshot-samlere (alle best-effort — må aldrig kaste)
# ---------------------------------------------------------------------------

def _file_inventory() -> list[dict]:
    root = Path(".")
    out = []
    for p in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            out.append({"file": str(p), "bytes": p.stat().st_size, "lines": text.count("\n") + 1})
        except Exception:
            continue
    return out


def _recent_git_diff(days: int = 7) -> str:
    try:
        res = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--stat", "--oneline"],
            capture_output=True, text=True, timeout=30,
        )
        return res.stdout[:8000]
    except Exception as e:  # git ikke tilgængelig / ikke et repo
        return f"(git diff utilgængelig: {e})"


def _run_profiling() -> list[dict]:
    """Profilér indikator + signal-generering på syntetisk OHLCV. Top-25 efter cumtime."""
    try:
        import numpy as np
        import pandas as pd

        from data.indicators import add_all
        from strategies.registry import load_strategies

        rng = np.random.default_rng(42)
        n = 500
        price = 100 + np.cumsum(rng.normal(0, 1, n))
        base = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="4h"),
            "open": price, "high": price + 1, "low": price - 1,
            "close": price + rng.normal(0, 0.5, n),
            "volume": rng.uniform(100, 1000, n),
        })
        strategies = load_strategies().get_enabled(
            ["trend_momentum", "reversal_context", "volatility_breakout"]
        )

        def workload():
            for _ in range(20):
                df = add_all(base.copy())
                for strat in strategies:
                    try:
                        strat.generate_signal(df, "BTC/USDT")
                    except Exception:
                        pass

        profiler = cProfile.Profile()
        profiler.enable()
        workload()
        profiler.disable()

        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
        stats.print_stats(25)
        # Parse pstats-linjerne til strukturerede rækker. En rigtig stat-linje er:
        #   ncalls  tottime  percall  cumtime  percall  filename:lineno(function)
        # Header/summary-linjer filtreres fra ved at kræve at tottime+cumtime er floats.
        rows = []
        for line in stream.getvalue().splitlines():
            parts = line.split()
            if len(parts) < 6:
                continue
            ncalls = parts[0].split("/")[0]  # "20" eller "20/1" (rekursion)
            if not ncalls.isdigit():
                continue
            try:
                tottime, cumtime = float(parts[1]), float(parts[3])
            except ValueError:
                continue
            rows.append({
                "ncalls": parts[0], "tottime": tottime, "cumtime": cumtime,
                "func": " ".join(parts[5:]),
            })
        return rows[:25]
    except Exception as e:
        logger.warning("Profilering fejlede: %s", e)
        return []


def _parse_coverage() -> str:
    """Kør pytest med coverage (best-effort). Kræver pytest-cov; ellers en note."""
    try:
        res = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "--cov=.", "--cov-report=term-missing", "-q"],
            capture_output=True, text=True, timeout=300,
        )
        out = res.stdout
        # Returnér kun TOTAL-linjen + evt. fejl for at spare tokens.
        total = [ln for ln in out.splitlines() if ln.strip().startswith("TOTAL")]
        return "\n".join(total) or out[-1500:]
    except Exception as e:
        return f"(coverage utilgængelig — pytest-cov ikke installeret? {e})"


def _load_latest_backtest() -> str:
    try:
        d = Path("backtest_results")
        if not d.exists():
            return "(ingen backtest_results/)"
        files = sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return "(ingen backtest-CSV'er)"
        return f"{files[0].name}:\n{files[0].read_text(errors='ignore')[:3000]}"
    except Exception as e:
        return f"(backtest-summary utilgængelig: {e})"


def collect_codebase_snapshot(include_profiling: bool, include_git_diff: bool) -> dict:
    return {
        "files": _file_inventory(),
        "git_diff": _recent_git_diff(7) if include_git_diff else "(deaktiveret)",
        "profile": _run_profiling() if include_profiling else [],
        "coverage": _parse_coverage() if include_profiling else "(sprunget over)",
        "backtest_summary": _load_latest_backtest(),
    }


# ---------------------------------------------------------------------------
# Prompt + kørsel
# ---------------------------------------------------------------------------

_ARCH_PROMPT = (
    "Du er en senior software-arkitekt med erfaring i algoritmiske trading-systemer.\n"
    "Nedenfor er en snapshot af en Python trading-bot: filstruktur, git diffs fra ugen, "
    "profileringsdata (cpu-tid pr. funktion), test-coverage og seneste backtest-resultater.\n\n"
    "Analyser og find:\n"
    "1. PERFORMANCE: hvilke funktioner bruger uforholdsmæssig meget CPU? caching-muligheder?\n"
    "2. ARKITEKTUR: anti-patterns, unødig kompleksitet, manglende separation of concerns?\n"
    "3. PÅLIDELIGHED: ubehandlede edge cases, manglende error handling, risikable antagelser?\n"
    "4. TESTDÆKNING: hvilke kritiske codepaths mangler tests?\n"
    "5. SAMMENHÆNG: inkonsistenser mellem hvad strategierne lover og hvad execution leverer?\n\n"
    "For hvert fund: estimer impact (high/medium/low) og effort (hours 1-8). Prioritér efter "
    "impact/effort.\n\n"
    "Svar KUN med JSON-array:\n"
    '[{"type":"architecture_suggestion","category":"performance|architecture|reliability|'
    'testing|consistency","file":"path/til/fil.py","description":"...","suggested_change":"...",'
    '"impact":"high|medium|low","effort_hours":0,"confidence":0.0}]\n\n'
    "SNAPSHOT:\n"
)


def run_weekly(config: dict, dry_run: bool = False) -> dict:
    rcfg = config["reflection"]
    if not rcfg.get("enabled", False):
        logger.info("reflection.enabled=false — springer weekly over.")
        return {"skipped": True}

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    wcfg = rcfg["weekly"]
    # I dry-run holder vi kørslen let: ingen profilering/coverage.
    include_profiling = wcfg.get("include_profiling", True) and not dry_run
    include_git_diff = wcfg.get("include_git_diff", True)

    snapshot = collect_codebase_snapshot(include_profiling, include_git_diff)
    analyst = ReflectionAnalyst(rcfg["anthropic_model"], store=None)

    prompt = _ARCH_PROMPT + json.dumps(snapshot, default=str)[:60000]
    findings = analyst.analyse(prompt, context_text="")
    logger.info("Weekly: %d arkitektur-fund.", len(findings))

    # Phase 5: research-baserede A/B-eksperiment-forslag (curated viden, aldrig auto-apply).
    research_cfg = rcfg.get("research", {})
    research_section = ""
    if research_cfg.get("enabled", True):
        try:
            researcher = Researcher(enable_web=research_cfg.get("web_search", False))
            research_section = researcher.build_ab_experiment_suggestions(_STRATEGY_IDS)
        except Exception as e:  # research må aldrig vælte weekly
            logger.warning("Kunne ikke bygge research-afsnit: %s", e)

    report_path = write_weekly_report(date_str, findings, research_section=research_section)
    reporter = TelegramReporter(config)
    reporter.send(f"📐 Weekly arkitektur-rapport {date_str} — {len(findings)} fund.\nSe {report_path}")

    summary = {
        "date": date_str,
        "findings": len(findings),
        "report_path": report_path,
        "dry_run": dry_run,
        "files_scanned": len(snapshot["files"]),
    }
    logger.info("Weekly færdig: %s", summary)
    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Loop B — Weekly arkitektur-analyse")
    parser.add_argument("--dry-run", action="store_true", help="Let kørsel, apply intet")
    args = parser.parse_args()

    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    run_weekly(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
