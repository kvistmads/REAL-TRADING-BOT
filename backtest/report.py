from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("backtest_results")


def print_metrics(metrics: dict, meta: dict) -> None:
    """Print et pænt resumé til terminalen."""
    pf = metrics["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    print()
    print("=" * 60)
    print(
        f"  {meta.get('strategy', '?')} | {meta.get('symbol', '?')} | "
        f"{meta.get('timeframe', '?')}  "
        f"({meta.get('from', '?')} → {meta.get('to', '?')})"
    )
    print("=" * 60)
    print(
        f"  Trades: {metrics['total_trades']} | "
        f"Win rate: {metrics['win_rate']}% | "
        f"Avg P&L: {metrics['avg_pnl_pct']:+.2f}% | "
        f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%"
    )
    print(
        f"  Wins: {metrics['wins']} | Losses: {metrics['losses']} | "
        f"Profit factor: {pf_str}"
    )
    print(
        f"  Avg win: {metrics['avg_win_pct']:+.2f}% | "
        f"Avg loss: {metrics['avg_loss_pct']:+.2f}% | "
        f"Total P&L: {metrics['total_pnl_pct']:+.2f}% ({metrics['total_pnl']:+.2f} USDT)"
    )
    print(f"  Sharpe (annualized): {metrics['sharpe']:.2f}")
    print("=" * 60)


def save_csv(trades: list[dict], meta: dict) -> Path:
    """Gem alle trades til CSV under backtest_results/."""
    RESULTS_DIR.mkdir(exist_ok=True)
    # Symboler er på formen BTC/USDT — skråstregen ville ellers blive læst som undermappe.
    symbol = meta["symbol"].replace("/", "-")
    filename = f"{meta['strategy']}_{symbol}_{meta['timeframe']}.csv"
    path = RESULTS_DIR / filename

    fields = [
        "symbol", "side", "strategy_id", "entry_time", "exit_time",
        "entry_price", "exit_price", "pnl", "pnl_pct", "reason", "bars_held",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            writer.writerow(t)

    print(f"  Resultater gemt til {path}")
    return path


# ---------------------------------------------------------------------------
# HTML-rapport (Del C)
# ---------------------------------------------------------------------------

# Farver pr. strategi — genbruges på tværs af alle charts så samme strategi har
# samme farve i hele rapporten.
STRATEGY_COLORS = ["#4aa3ff", "#7c5cff", "#ffb454", "#29d391", "#ff5c6c"]

REASON_COLORS = {
    "take_profit": "#29d391",
    "stop_loss": "#ff5c6c",
    "end_of_data": "#8b94a7",
}

CHARTJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"


def _as_dt(value) -> datetime | None:
    """Normalisér entry/exit-time til datetime. pandas.Timestamp er en datetime-subklasse."""
    if isinstance(value, datetime):
        return value
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _pf_str(pf) -> str:
    return "∞" if pf == float("inf") else f"{pf:.2f}"


def _pf_num(pf):
    """JSON/sortérbar udgave af profit factor — Infinity er ikke gyldig JSON."""
    return None if pf == float("inf") else round(float(pf), 3)


def _histogram(values: list[int], bins: int = 12) -> dict:
    """Simpelt equal-width histogram. Returnerer {'labels': [...], 'values': [...]}."""
    if not values:
        return {"labels": [], "values": []}
    lo, hi = min(values), max(values)
    if hi == lo:
        return {"labels": [str(lo)], "values": [len(values)]}
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    labels = [
        f"{int(lo + i * width)}–{int(lo + (i + 1) * width)}" for i in range(bins)
    ]
    return {"labels": labels, "values": counts}


def _ordered(rows: list[dict], key: str) -> list[str]:
    """Unikke værdier i den rækkefølge de optræder i rows (bevarer config-orden)."""
    seen: list[str] = []
    for r in rows:
        if r[key] not in seen:
            seen.append(r[key])
    return seen


def _build_payload(rows: list[dict], all_trades: list[dict],
                   strategies: list[str], symbols: list[str]) -> dict:
    """Aggregér alt chart-data i Python — JS'en tegner kun det den får."""
    by_row = {(r["strategy"], r["symbol"]): r for r in rows}

    # Sektion 4 — total PnL% pr. strategi × symbol
    pnl_by_strategy = {
        s: {
            "labels": symbols,
            "values": [
                round(float(by_row.get((s, sym), {}).get("total_pnl_pct", 0.0)), 2)
                for sym in symbols
            ],
        }
        for s in strategies
    }

    # Sektion 5 — exit-årsager pr. strategi
    reason_counts: dict[str, dict[str, int]] = {
        s: dict.fromkeys(REASON_COLORS, 0) for s in strategies
    }
    for t in all_trades:
        sid = t.get("strategy_id")
        reason = t.get("reason")
        if sid in reason_counts and reason in reason_counts[sid]:
            reason_counts[sid][reason] += 1

    # Sektion 6 — kumulativ PnL%-kurve pr. symbol, én linje pr. strategi.
    # Chart.js' time-scale kræver en date-adapter (ekstra CDN, ikke tilladt), så
    # x-aksen er en kategori-akse over unionen af alle entry_times for symbolet;
    # huller udfyldes med null + spanGaps.
    cumulative: dict[str, dict] = {}
    for sym in symbols:
        sym_trades = [
            (dt, t) for t in all_trades if t.get("symbol") == sym
            if (dt := _as_dt(t.get("entry_time"))) is not None
        ]
        if not sym_trades:
            cumulative[sym] = {"labels": [], "series": []}
            continue
        times = sorted({dt for dt, _ in sym_trades})
        pos = {dt: i for i, dt in enumerate(times)}
        series = []
        for s in strategies:
            data: list[float | None] = [None] * len(times)
            cum = 0.0
            for dt, t in sorted((p for p in sym_trades if p[1].get("strategy_id") == s),
                                key=lambda p: p[0]):
                cum += float(t.get("pnl_pct", 0.0))
                data[pos[dt]] = round(cum, 3)
            if any(v is not None for v in data):
                series.append({"label": s, "data": data})
        cumulative[sym] = {
            "labels": [dt.strftime("%Y-%m-%d") for dt in times],
            "series": series,
        }

    # Sektion 7 — bars_held-fordeling pr. strategi
    bars_by_strategy: dict[str, list[int]] = defaultdict(list)
    for t in all_trades:
        if t.get("strategy_id") in reason_counts:
            bars_by_strategy[t["strategy_id"]].append(int(t.get("bars_held", 0)))

    return {
        "strategies": strategies,
        "symbols": symbols,
        "colors": {s: STRATEGY_COLORS[i % len(STRATEGY_COLORS)]
                   for i, s in enumerate(strategies)},
        "reasonColors": REASON_COLORS,
        "pnlByStrategy": pnl_by_strategy,
        "exitReasons": reason_counts,
        "cumulative": cumulative,
        "barsHist": {s: _histogram(bars_by_strategy.get(s, [])) for s in strategies},
    }


def _header_html(rows: list[dict], periods: dict) -> str:
    """Sektion 1 — titel, køredato, periode pr. asset-klasse, godkendt X/N."""
    n_pass = sum(1 for r in rows if r["pass"])
    total = len(rows)
    ratio = n_pass / total if total else 0.0
    cls = "hi" if ratio >= 0.5 else ("mid" if n_pass else "lo")

    spans: dict[str, list] = {}
    for sym, (start, end) in (periods or {}).items():
        ac = BaseStrategy.get_asset_class(sym)
        s, e = _as_dt(start), _as_dt(end)
        if s is None or e is None:
            continue
        if ac not in spans:
            spans[ac] = [s, e]
        else:
            spans[ac][0] = min(spans[ac][0], s)
            spans[ac][1] = max(spans[ac][1], e)

    chips = "".join(
        f'<span class="chip"><b>{ac}</b> {s.date()} → {e.date()}</span>'
        for ac, (s, e) in sorted(spans.items())
    ) or '<span class="chip muted">ingen periodedata</span>'

    return f"""
<header>
  <div>
    <h1>Backtest-rapport</h1>
    <div class="muted">Kørt {date.today().isoformat()} · {total} kombinationer
      ({len(_ordered(rows, 'strategy'))} strategier × {len(_ordered(rows, 'symbol'))} symboler)</div>
  </div>
  <div class="spacer"></div>
  <div class="scorecard {cls}">
    <div class="label">Godkendt til paper mode</div>
    <div class="value">{n_pass}/{total}</div>
  </div>
</header>
<div class="panel">
  <h2>Dataperiode pr. asset-klasse</h2>
  <div class="chips">{chips}</div>
</div>
"""


def _wr_class(r: dict) -> str:
    if not r["trades"]:
        return "na"
    wr = r["win_rate"]
    return "hi" if wr > 60 else ("mid" if wr >= 50 else "lo")


def _pf_class(r: dict) -> str:
    if not r["trades"]:
        return "na"
    pf = r["profit_factor"]
    if pf == float("inf") or pf >= 1.3:
        return "hi"
    return "mid" if pf >= 1.0 else "lo"


def _heatmap_html(rows: list[dict], strategies: list[str], symbols: list[str]) -> str:
    """Sektion 2 — to 3×6 grids side om side: win rate og profit factor."""
    by_row = {(r["strategy"], r["symbol"]): r for r in rows}

    def grid(title: str, value_fn, class_fn) -> str:
        head = "".join(f"<th>{s}</th>" for s in symbols)
        body = ""
        for strat in strategies:
            cells = ""
            for sym in symbols:
                r = by_row.get((strat, sym))
                if r is None:
                    cells += '<td class="hm na">—</td>'
                else:
                    cells += f'<td class="hm {class_fn(r)}">{value_fn(r)}</td>'
            body += f"<tr><th class='rowhead'>{strat}</th>{cells}</tr>"
        return f"""
<div class="panel">
  <h2>{title}</h2>
  <div class="scroll-x">
    <table class="heatmap"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>
  </div>
</div>"""

    wr = grid("Win rate", lambda r: f"{r['win_rate']:.1f}%", _wr_class)
    pf = grid("Profit factor", lambda r: _pf_str(r["profit_factor"]), _pf_class)
    return f'<div class="grid-2">{wr}{pf}</div>'


def _table_html(rows: list[dict]) -> str:
    """Sektion 3 — komplet suite-tabel, sorterbar ved klik på kolonnehoved."""
    cols = [
        ("Strategi", "strategy", "text"), ("Symbol", "symbol", "text"),
        ("Trades", "trades", "num"), ("Win%", "win_rate", "num"),
        ("PF", "profit_factor", "num"), ("MaxDD%", "max_dd", "num"),
        ("Sharpe", "sharpe", "num"), ("PnL%", "total_pnl_pct", "num"),
        ("W", "wins", "num"), ("L", "losses", "num"),
        ("AvgW%", "avg_win_pct", "num"), ("AvgL%", "avg_loss_pct", "num"),
        ("Bars", "avg_bars_held", "num"), ("OK", "pass", "num"),
    ]
    head = "".join(
        f'<th data-type="{t}" title="Klik for at sortere">{label}</th>'
        for label, _, t in cols
    )

    body = ""
    for r in rows:
        tds = ""
        for _, key, typ in cols:
            v = r.get(key)
            if key == "pass":
                tds += f'<td data-v="{1 if v else 0}">{"✅" if v else "❌"}</td>'
            elif key == "profit_factor":
                tds += f'<td data-v="{_pf_num(v) if _pf_num(v) is not None else 9999}">{_pf_str(v)}</td>'
            elif typ == "num":
                cls = ""
                if key in ("total_pnl_pct", "sharpe"):
                    cls = ' class="pos"' if float(v) > 0 else (
                        ' class="neg"' if float(v) < 0 else ' class="flat"')
                tds += f'<td data-v="{v}"{cls}>{v}</td>'
            else:
                tds += f"<td>{v}</td>"
        body += f'<tr class="{"ok" if r["pass"] else ""}">{tds}</tr>'

    return f"""
<div class="panel">
  <h2>Suite-resultater — alle kombinationer</h2>
  <table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
  <div class="muted small">Tærskler: trades &gt; 20 · win rate &gt; 50% · PF &gt; 1.3 ·
    max DD &gt; -20% · Sharpe &gt; 0.8</div>
</div>
"""


def _monthly_html(all_trades: list[dict], strategies: list[str]) -> str:
    """Sektion 8 — månedlig PnL%-heatmap pr. strategi."""
    totals: dict[tuple[str, str], float] = defaultdict(float)
    months: set[str] = set()
    for t in all_trades:
        dt = _as_dt(t.get("exit_time")) or _as_dt(t.get("entry_time"))
        if dt is None:
            continue
        key = dt.strftime("%Y-%m")
        months.add(key)
        totals[(t.get("strategy_id"), key)] += float(t.get("pnl_pct", 0.0))

    if not months:
        return ('<div class="panel"><h2>Månedlig performance</h2>'
                '<div class="empty">Ingen trades med tidsstempel.</div></div>')

    ordered_months = sorted(months)
    head = "".join(f"<th>{m[2:]}</th>" for m in ordered_months)
    body = ""
    for s in strategies:
        cells = ""
        for m in ordered_months:
            v = totals.get((s, m))
            if v is None:
                cells += '<td class="hm na">·</td>'
            else:
                cls = "hi" if v > 0 else ("lo" if v < 0 else "na")
                cells += f'<td class="hm {cls}">{v:+.1f}</td>'
        body += f"<tr><th class='rowhead'>{s}</th>{cells}</tr>"

    return f"""
<div class="panel">
  <h2>Månedlig performance (sum PnL% pr. måned)</h2>
  <div class="scroll-x">
    <table class="heatmap"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>
  </div>
</div>
"""


_CSS = """
  :root {
    --bg: #0b0e14; --panel: #141922; --panel-2: #1b2130; --border: #262d3d;
    --text: #e6e9ef; --muted: #8b94a7; --green: #29d391; --red: #ff5c6c;
    --amber: #ffb454; --blue: #4aa3ff; --accent: #7c5cff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 24px;
  }
  .wrap { max-width: 1400px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em;
       color: var(--muted); margin: 0 0 14px; }
  h3 { font-size: 13px; margin: 0 0 10px; color: var(--text); }
  h2.section-title { margin: 26px 2px 12px; color: var(--text); font-size: 12px; }
  header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
  .spacer { flex: 1; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; margin-top: 10px; }
  .panel { background: var(--panel); border: 1px solid var(--border);
           border-radius: 12px; padding: 18px; margin-bottom: 18px; }
  .scorecard { border: 1px solid var(--border); border-radius: 12px;
               padding: 12px 20px; background: var(--panel); text-align: right; }
  .scorecard .label { color: var(--muted); font-size: 12px; }
  .scorecard .value { font-size: 26px; font-weight: 700; margin-top: 2px; }
  .scorecard.hi .value { color: var(--green); }
  .scorecard.mid .value { color: var(--amber); }
  .scorecard.lo .value { color: var(--red); }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { padding: 4px 12px; border-radius: 8px; font-size: 12px;
          border: 1px solid var(--border); background: var(--panel-2); }
  .chip b { color: var(--blue); font-weight: 600; text-transform: uppercase; font-size: 11px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: right; padding: 7px 9px; border-bottom: 1px solid var(--border);
           white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--muted); font-weight: 600; font-size: 11px;
             text-transform: uppercase; letter-spacing: .04em; }
  table.sortable thead th { cursor: pointer; user-select: none; }
  table.sortable thead th:hover { color: var(--text); }
  table.sortable thead th.sorted-asc::after { content: " ▲"; color: var(--blue); }
  table.sortable thead th.sorted-desc::after { content: " ▼"; color: var(--blue); }
  tbody tr:hover { background: var(--panel-2); }
  tbody tr.ok { background: rgba(41,211,145,.07); }
  tbody tr.ok:hover { background: rgba(41,211,145,.13); }
  .pos { color: var(--green); } .neg { color: var(--red); } .flat { color: var(--muted); }
  /* Kompakte celler — to 6-kolonners heatmaps skal kunne stå side om side i
     .grid-2 uden at blive klippet (.scroll-x er sikkerhedsnettet på smalle skærme). */
  .heatmap td, .heatmap th { text-align: center; padding: 6px 5px; font-size: 11px; }
  .heatmap th.rowhead { text-align: left; color: var(--text); padding-right: 10px;
                        font-size: 11px; text-transform: none; letter-spacing: 0; }
  td.hm { font-variant-numeric: tabular-nums; font-weight: 600; }
  td.hm.hi { background: rgba(41,211,145,.18); color: var(--green); }
  td.hm.mid { background: rgba(255,180,84,.18); color: var(--amber); }
  td.hm.lo { background: rgba(255,92,108,.16); color: var(--red); }
  td.hm.na { color: var(--muted); }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
  .chart-box { position: relative; height: 240px; }
  .chart-box.tall { height: 280px; }
  .empty { color: var(--muted); padding: 10px 0; }
  .scroll-x { overflow-x: auto; }
  .warn { background: rgba(255,180,84,.12); border: 1px solid rgba(255,180,84,.35);
          color: var(--amber); border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; }
  @media (max-width: 1200px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    body { padding: 14px; }
  }
"""

_JS = """
// --- Sorterbar tabel (sektion 3) -----------------------------------------
document.querySelectorAll('table.sortable').forEach(function (table) {
  var headers = table.querySelectorAll('thead th');
  headers.forEach(function (th, idx) {
    th.addEventListener('click', function () {
      var tbody = table.tBodies[0];
      var rows = Array.prototype.slice.call(tbody.rows);
      var numeric = th.dataset.type === 'num';
      var asc = !th.classList.contains('sorted-asc');
      headers.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
      rows.sort(function (a, b) {
        var x = a.cells[idx], y = b.cells[idx];
        if (numeric) {
          var nx = parseFloat(x.dataset.v), ny = parseFloat(y.dataset.v);
          if (isNaN(nx)) nx = -Infinity;
          if (isNaN(ny)) ny = -Infinity;
          return asc ? nx - ny : ny - nx;
        }
        return asc ? x.textContent.localeCompare(y.textContent)
                   : y.textContent.localeCompare(x.textContent);
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
});

// --- Charts ---------------------------------------------------------------
if (typeof Chart === 'undefined') {
  document.getElementById('cdn-warning').style.display = 'block';
} else {
  Chart.defaults.color = '#8b94a7';
  Chart.defaults.borderColor = '#262d3d';
  Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation = false;

  var GREEN = '#29d391', RED = '#ff5c6c';
  var gridCfg = { grid: { color: '#262d3d' }, ticks: { font: { size: 10 } } };

  // Sektion 4 — total PnL% pr. strategi
  D.strategies.forEach(function (s) {
    var d = D.pnlByStrategy[s];
    new Chart(document.getElementById('pnl-' + slug(s)), {
      type: 'bar',
      data: {
        labels: d.labels,
        datasets: [{
          data: d.values,
          backgroundColor: d.values.map(function (v) { return v >= 0 ? GREEN : RED; }),
          borderRadius: 4
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { x: gridCfg, y: gridCfg }
      }
    });
  });

  // Sektion 5 — exit-årsager (donut)
  D.strategies.forEach(function (s) {
    var counts = D.exitReasons[s];
    var labels = Object.keys(counts);
    new Chart(document.getElementById('exit-' + slug(s)), {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: labels.map(function (k) { return counts[k]; }),
          backgroundColor: labels.map(function (k) { return D.reasonColors[k]; }),
          borderColor: '#141922', borderWidth: 2
        }]
      },
      options: {
        cutout: '58%',
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } }
      }
    });
  });

  // Sektion 6 — kumulativ PnL pr. symbol
  D.symbols.forEach(function (sym) {
    var c = D.cumulative[sym];
    new Chart(document.getElementById('cum-' + slug(sym)), {
      type: 'line',
      data: {
        labels: c.labels,
        datasets: c.series.map(function (s) {
          return {
            label: s.label, data: s.data,
            borderColor: D.colors[s.label], backgroundColor: D.colors[s.label],
            borderWidth: 2, pointRadius: 0, tension: 0.15, spanGaps: true
          };
        })
      },
      options: {
        plugins: { legend: { labels: { boxWidth: 10, font: { size: 11 } } } },
        interaction: { mode: 'nearest', intersect: false },
        scales: {
          x: { grid: { color: '#262d3d' },
               ticks: { maxTicksLimit: 6, font: { size: 10 } } },
          y: gridCfg
        }
      }
    });
  });

  // Sektion 7 — bars_held histogram
  D.strategies.forEach(function (s) {
    var h = D.barsHist[s];
    new Chart(document.getElementById('bars-' + slug(s)), {
      type: 'bar',
      data: {
        labels: h.labels,
        datasets: [{ data: h.values, backgroundColor: D.colors[s], borderRadius: 3 }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { x: gridCfg, y: gridCfg }
      }
    });
  });
}
"""


def _chart_grid(ids: list[str], titles: list[str], prefix: str,
                tall: bool = False) -> str:
    boxes = "".join(
        f'<div class="panel"><h3>{t}</h3>'
        f'<div class="chart-box{" tall" if tall else ""}">'
        f'<canvas id="{prefix}-{i}"></canvas></div></div>'
        for i, t in zip(ids, titles)
    )
    return f'<div class="grid-3">{boxes}</div>'


def _slug(value: str) -> str:
    return value.replace("/", "-").replace(" ", "-").lower()


def generate_html_report(rows: list[dict], all_trades: list[dict],
                         periods: dict, out_dir: Path | None = None) -> Path:
    """Skriv en selvstændig HTML-rapport med alle 8 sektioner.

    Read-only output: læser kun de dicts suiten allerede har bygget, rører hverken
    DB eller simulation. Chart-data aggregeres i Python og indlejres som JSON.
    """
    results_dir = out_dir or RESULTS_DIR
    results_dir.mkdir(exist_ok=True)
    path = results_dir / f"report_{date.today().isoformat()}.html"

    strategies = _ordered(rows, "strategy")
    symbols = _ordered(rows, "symbol")
    payload = _build_payload(rows, all_trades, strategies, symbols)

    strat_slugs = [_slug(s) for s in strategies]
    sym_slugs = [_slug(s) for s in symbols]

    sections = [
        _header_html(rows, periods),
        _heatmap_html(rows, strategies, symbols),
        _table_html(rows),
        '<h2 class="section-title">Total PnL% pr. strategi</h2>',
        _chart_grid(strat_slugs, strategies, "pnl"),
        '<h2 class="section-title">Exit-årsager</h2>',
        _chart_grid(strat_slugs, strategies, "exit"),
        '<h2 class="section-title">Kumulativ PnL% pr. symbol</h2>',
        _chart_grid(sym_slugs, symbols, "cum", tall=True),
        '<h2 class="section-title">Fordeling af bars held</h2>',
        _chart_grid(strat_slugs, strategies, "bars"),
        _monthly_html(all_trades, strategies),
    ]

    html = f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest-rapport — {date.today().isoformat()}</title>
<script src="{CHARTJS_CDN}"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<div id="cdn-warning" class="warn" style="display:none">
  Chart.js kunne ikke hentes fra CDN — tabeller og heatmaps virker, men graferne er tomme.
  Åbn rapporten med internetforbindelse.
</div>
{"".join(sections)}
<div class="muted small">Genereret af backtest/report.py · {len(all_trades)} trades i alt</div>
</div>
<script>
var D = {json.dumps(payload)};
function slug(v) {{ return v.replace(/\\//g, '-').replace(/ /g, '-').toLowerCase(); }}
{_JS}
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    print(f"  HTML-rapport gemt til {path}")
    return path
