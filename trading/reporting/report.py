#!/usr/bin/env python3
"""
Generate a self-contained HTML trading report with interactive charts.
Embeds Chart.js (CDN) for equity curve, drawdown, strategy breakdown, and trade log.
"""
import json
from datetime import datetime
from typing import Dict, Any


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>JP Morgan Trading System — Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0a0e1a;
    --card: #0f1629;
    --border: #1e2d4e;
    --accent: #00b4d8;
    --green: #00d97e;
    --red: #ff4d6d;
    --gold: #ffd60a;
    --text: #e0e6f0;
    --muted: #6b7c9d;
    --font: 'Segoe UI', system-ui, sans-serif;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    min-height: 100vh;
  }}

  /* Header */
  .header {{
    background: linear-gradient(135deg, #0a0e1a 0%, #0d1f3c 50%, #0a1628 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .header-left h1 {{
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }}
  .header-left h1 span {{ color: var(--accent); }}
  .header-left p {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
  .badge {{
    background: rgba(0,180,216,0.12);
    border: 1px solid var(--accent);
    color: var(--accent);
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.05em;
  }}

  /* Layout */
  .container {{ max-width: 1400px; margin: 0 auto; padding: 32px 40px; }}

  /* KPI grid */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .kpi {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
  }}
  .kpi::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
  }}
  .kpi.positive::before {{ background: var(--green); }}
  .kpi.negative::before {{ background: var(--red); }}
  .kpi.neutral::before {{ background: var(--accent); }}
  .kpi.warning::before {{ background: var(--gold); }}
  .kpi-label {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
  .kpi-value {{
    font-size: 1.65rem;
    font-weight: 700;
    margin-top: 6px;
    font-variant-numeric: tabular-nums;
  }}
  .kpi-value.positive {{ color: var(--green); }}
  .kpi-value.negative {{ color: var(--red); }}
  .kpi-value.neutral {{ color: var(--accent); }}
  .kpi-sub {{ font-size: 0.75rem; color: var(--muted); margin-top: 4px; }}

  /* Chart cards */
  .chart-grid {{
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  .chart-grid-3 {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }}
  .card-title {{
    font-size: 0.82rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .card-title::before {{
    content: '';
    display: inline-block;
    width: 3px;
    height: 14px;
    background: var(--accent);
    border-radius: 2px;
  }}
  .chart-wrap {{ position: relative; height: 240px; }}
  .chart-wrap.tall {{ height: 300px; }}

  /* Trade Table */
  .table-wrap {{ overflow-x: auto; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    font-variant-numeric: tabular-nums;
  }}
  th {{
    text-align: left;
    padding: 10px 14px;
    background: rgba(30,45,78,0.6);
    color: var(--muted);
    font-size: 0.70rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 9px 14px;
    border-bottom: 1px solid rgba(30,45,78,0.4);
    white-space: nowrap;
  }}
  tr:hover td {{ background: rgba(0,180,216,0.04); }}
  .tp {{ color: var(--green); font-weight: 600; }}
  .sl {{ color: var(--red); font-weight: 600; }}
  .buy {{ color: #60d4f8; }}
  .sell {{ color: #f09eff; }}
  .pnl-pos {{ color: var(--green); }}
  .pnl-neg {{ color: var(--red); }}

  /* Strategy breakdown */
  .strat-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid rgba(30,45,78,0.4);
  }}
  .strat-row:last-child {{ border-bottom: none; }}
  .strat-name {{ flex: 1; font-size: 0.82rem; }}
  .strat-bar-wrap {{ flex: 2; height: 6px; background: rgba(30,45,78,0.8); border-radius: 3px; overflow: hidden; }}
  .strat-bar {{ height: 100%; border-radius: 3px; transition: width 0.8s ease; }}
  .strat-pnl {{ width: 100px; text-align: right; font-size: 0.80rem; font-weight: 600; }}
  .strat-wr {{ width: 55px; text-align: right; font-size: 0.76rem; color: var(--muted); }}

  /* Risk panel */
  .risk-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }}
  .risk-item {{ padding: 12px 16px; background: rgba(30,45,78,0.3); border-radius: 8px; }}
  .risk-item-label {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase; }}
  .risk-item-val {{ font-size: 1.05rem; font-weight: 700; margin-top: 2px; }}

  /* Footer */
  .footer {{
    text-align: center;
    padding: 24px;
    color: var(--muted);
    font-size: 0.75rem;
    border-top: 1px solid var(--border);
    margin-top: 40px;
  }}

  /* Responsive */
  @media (max-width: 900px) {{
    .chart-grid, .chart-grid-3 {{ grid-template-columns: 1fr; }}
    .container {{ padding: 20px; }}
    .header {{ padding: 20px; flex-direction: column; gap: 12px; }}
  }}
</style>
</head>
<body>

<header class="header">
  <div class="header-left">
    <h1>JP Morgan <span>Trading System</span></h1>
    <p>Multi-Strategy Backtest Report &bull; {run_date} &bull; {n_bars} bars &bull; {n_symbols} symbols</p>
  </div>
  <span class="badge">BACKTEST</span>
</header>

<div class="container">

  <!-- KPI Row -->
  <div class="kpi-grid">
    <div class="kpi {return_class}">
      <div class="kpi-label">Total Return</div>
      <div class="kpi-value {return_class}">{total_return}%</div>
      <div class="kpi-sub">Initial: {initial_capital}</div>
    </div>
    <div class="kpi neutral">
      <div class="kpi-label">Final Equity</div>
      <div class="kpi-value neutral">{final_equity}</div>
      <div class="kpi-sub">Cash: {cash}</div>
    </div>
    <div class="kpi {realized_class}">
      <div class="kpi-label">Realized PnL</div>
      <div class="kpi-value {realized_class}">{realized_pnl}</div>
      <div class="kpi-sub">Commission: {commission}</div>
    </div>
    <div class="kpi warning">
      <div class="kpi-label">Max Drawdown</div>
      <div class="kpi-value warning">{max_dd}%</div>
      <div class="kpi-sub">Sharpe: {sharpe}</div>
    </div>
    <div class="kpi neutral">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-value neutral">{win_rate}%</div>
      <div class="kpi-sub">{winners}W / {losers}L</div>
    </div>
    <div class="kpi positive">
      <div class="kpi-label">Profit Factor</div>
      <div class="kpi-value positive">{profit_factor}x</div>
      <div class="kpi-sub">Expectancy: {expectancy}/trade</div>
    </div>
    <div class="kpi neutral">
      <div class="kpi-label">Total Trades</div>
      <div class="kpi-value neutral">{total_trades}</div>
      <div class="kpi-sub">TP: {tp_count} &bull; SL: {sl_count}</div>
    </div>
    <div class="kpi neutral">
      <div class="kpi-label">Avg Win / Avg Loss</div>
      <div class="kpi-value neutral">{rr_ratio}R</div>
      <div class="kpi-sub">Win: {avg_win} / Loss: {avg_loss}</div>
    </div>
  </div>

  <!-- Equity Curve + Drawdown -->
  <div class="chart-grid">
    <div class="card">
      <div class="card-title">Equity Curve</div>
      <div class="chart-wrap tall"><canvas id="equityChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Drawdown</div>
      <div class="chart-wrap tall"><canvas id="ddChart"></canvas></div>
    </div>
  </div>

  <!-- Strategy breakdown + Pie + TP/SL distribution -->
  <div class="chart-grid-3">
    <div class="card">
      <div class="card-title">Strategy PnL Breakdown</div>
      {strategy_html}
    </div>
    <div class="card">
      <div class="card-title">Trades by Strategy</div>
      <div class="chart-wrap"><canvas id="stratPie"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Trade Outcome Distribution</div>
      <div class="chart-wrap"><canvas id="outcomeChart"></canvas></div>
    </div>
  </div>

  <!-- Trade Log -->
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">Recent Trade Log</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Order ID</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Entry</th>
            <th>TP Level</th>
            <th>SL Level</th>
            <th>Exit</th>
            <th>Outcome</th>
            <th>PnL</th>
            <th>Strategy</th>
          </tr>
        </thead>
        <tbody>
          {trade_rows}
        </tbody>
      </table>
    </div>
  </div>

</div><!-- /container -->

<footer class="footer">
  JP Morgan Trading System &bull; Generated {run_date} &bull; For internal use only
</footer>

<script>
const eq = {equity_json};
const dd = {dd_json};
const labels = {labels_json};

/* Chart defaults */
Chart.defaults.color = '#6b7c9d';
Chart.defaults.borderColor = '#1e2d4e';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size = 11;

/* Equity Curve */
new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      label: 'Equity',
      data: eq,
      borderColor: '#00b4d8',
      backgroundColor: 'rgba(0,180,216,0.07)',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: true,
      tension: 0.3
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }}, tooltip: {{
      callbacks: {{ label: ctx => ' $' + ctx.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}}) }}
    }} }},
    scales: {{
      x: {{ display: false }},
      y: {{
        ticks: {{ callback: v => '$' + (v/1e6).toFixed(2) + 'M' }},
        grid: {{ color: '#1e2d4e' }}
      }}
    }}
  }}
}});

/* Drawdown */
new Chart(document.getElementById('ddChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      label: 'Drawdown %',
      data: dd,
      borderColor: '#ff4d6d',
      backgroundColor: 'rgba(255,77,109,0.10)',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: true,
      tension: 0.3
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{
      callbacks: {{ label: ctx => ' ' + ctx.parsed.y.toFixed(2) + '%' }}
    }} }},
    scales: {{
      x: {{ display: false }},
      y: {{
        ticks: {{ callback: v => v.toFixed(1) + '%' }},
        grid: {{ color: '#1e2d4e' }}
      }}
    }}
  }}
}});

/* Strategy Pie */
const stratData = {strat_pie_json};
new Chart(document.getElementById('stratPie'), {{
  type: 'doughnut',
  data: {{
    labels: stratData.labels,
    datasets: [{{
      data: stratData.trades,
      backgroundColor: ['#00b4d8','#00d97e','#ffd60a','#f09eff','#ff4d6d','#60d4f8'],
      borderWidth: 0,
      hoverOffset: 6
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    cutout: '62%',
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 10, padding: 12 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.label + ': ' + ctx.parsed + ' trades' }} }}
    }}
  }}
}});

/* Outcome Distribution */
const outData = {outcome_json};
new Chart(document.getElementById('outcomeChart'), {{
  type: 'bar',
  data: {{
    labels: outData.labels,
    datasets: [{{
      data: outData.values,
      backgroundColor: outData.colors,
      borderRadius: 4,
      borderSkipped: false,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{
      callbacks: {{ label: ctx => ' $' + ctx.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}}) }}
    }} }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{
        ticks: {{ callback: v => '$' + v.toLocaleString() }},
        grid: {{ color: '#1e2d4e' }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def _fmt_money(val: float, sign: bool = True) -> str:
    prefix = "+" if sign and val > 0 else ""
    return f"{prefix}${val:,.2f}"


def _color_class(val: float) -> str:
    if val > 0:
        return "positive"
    if val < 0:
        return "negative"
    return "neutral"


def generate_html_report(
    backtest_result_json: str,
    output_path: str = "trading_report.html",
) -> None:
    with open(backtest_result_json) as f:
        data = json.load(f)

    p = data["portfolio_summary"]
    t = data["trade_analysis"]
    eq_curve = data.get("equity_curve", [])
    fills = data.get("recent_fills", [])

    # --- Equity / drawdown series ---
    labels = [s["ts"][11:16] for s in eq_curve]
    equities = [s["equity"] for s in eq_curve]
    dds = [s["drawdown_pct"] for s in eq_curve]

    # sample down to 200 points for smooth charts
    if len(labels) > 200:
        step = len(labels) // 200
        labels = labels[::step]
        equities = equities[::step]
        dds = dds[::step]

    # --- Strategy breakdown HTML ---
    by_strat = t.get("by_strategy", {})
    max_pnl = max((abs(v["total_pnl"]) for v in by_strat.values()), default=1)
    palette = ["#00b4d8", "#00d97e", "#ffd60a", "#f09eff", "#ff4d6d", "#60d4f8"]
    strategy_html_rows = ""
    for i, (sid, stats) in enumerate(by_strat.items()):
        pnl = stats["total_pnl"]
        bar_width = max(4, int(abs(pnl) / max_pnl * 100))
        bar_color = palette[i % len(palette)] if pnl >= 0 else "#ff4d6d"
        pnl_class = "pnl-pos" if pnl >= 0 else "pnl-neg"
        short_name = sid.replace("PLAN_", "").replace("_", " ").title()
        strategy_html_rows += f"""
        <div class="strat-row">
          <div class="strat-name">{short_name}</div>
          <div class="strat-bar-wrap"><div class="strat-bar" style="width:{bar_width}%;background:{bar_color}"></div></div>
          <div class="strat-pnl {pnl_class}">{_fmt_money(pnl)}</div>
          <div class="strat-wr">{stats['win_rate']:.0f}%</div>
        </div>"""

    # --- Strategy pie data ---
    strat_pie = {
        "labels": [s.replace("PLAN_", "").replace("_", " ").title() for s in by_strat],
        "trades": [v["trades"] for v in by_strat.values()],
    }

    # --- Outcome distribution (bucket PnL) ---
    pnl_values = [f.get("pnl", 0) for f in fills if "pnl" in f]
    buckets = [-15000, -5000, -2000, -500, 500, 2000, 5000, 15000, 40000]
    bucket_labels = ["<-15K", "-15K to -5K", "-5K to -2K", "-2K to -500", "-500 to +500",
                     "+500 to +2K", "+2K to +5K", "+5K to +15K", ">+15K"]
    bucket_counts = [0] * len(bucket_labels)
    for pnl in pnl_values:
        for j, threshold in enumerate(buckets):
            if pnl < threshold or j == len(buckets) - 1:
                bucket_counts[j] += pnl
                break
    outcome_colors = ["#ff4d6d" if v < 0 else "#00d97e" for v in bucket_counts]

    # --- Trade table rows ---
    # Reconstruct from fills: pair FILL events with close events
    fill_map = {}
    trade_rows_html = ""
    row_num = 1
    for ev in fills:
        oid = ev.get("order_id", "")
        if "fill" in ev and "tp" in ev:  # it's a FILL event
            fill_map[oid] = ev
        elif "event" in ev and ev["event"] in ("TP_HIT", "SL_HIT"):
            fill = fill_map.get(oid, {})
            outcome_class = "tp" if "TP" in ev["event"] else "sl"
            outcome_label = "TP HIT" if "TP" in ev["event"] else "SL HIT"
            pnl = ev.get("pnl", 0)
            pnl_class = "pnl-pos" if pnl > 0 else "pnl-neg"
            sym = ev.get("symbol", fill.get("symbol", ""))
            side_class = "buy" if fill.get("side", "") == "BUY" else "sell"
            trade_rows_html += f"""<tr>
              <td>{row_num}</td>
              <td style="font-family:monospace;font-size:0.75rem">{oid[:8]}</td>
              <td><strong>{sym}</strong></td>
              <td class="{side_class}">{fill.get('side','')}</td>
              <td>{fill.get('qty','')}</td>
              <td>${fill.get('fill',0):,.2f}</td>
              <td>${fill.get('tp',0) or 0:,.2f}</td>
              <td>${fill.get('sl',0) or 0:,.2f}</td>
              <td>${ev.get('close_price',0):,.2f}</td>
              <td class="{outcome_class}">{outcome_label}</td>
              <td class="{pnl_class}">{_fmt_money(pnl)}</td>
              <td style="color:var(--muted);font-size:0.75rem">{fill.get('strategy','')}</td>
            </tr>"""
            row_num += 1
        else:
            fill_map[oid] = ev

    if not trade_rows_html:
        # Fallback: show raw fill log
        for i, ev in enumerate(fills[:30]):
            if "fill" not in ev:
                continue
            pnl = ev.get("pnl", ev.get("rrr", 0))
            pnl_class = "pnl-pos" if (pnl or 0) > 0 else "pnl-neg"
            side_class = "buy" if ev.get("side", "") == "BUY" else "sell"
            trade_rows_html += f"""<tr>
              <td>{i+1}</td>
              <td style="font-family:monospace;font-size:0.75rem">{ev.get('order_id','')[:8]}</td>
              <td><strong>{ev.get('symbol','')}</strong></td>
              <td class="{side_class}">{ev.get('side','')}</td>
              <td>{ev.get('qty','')}</td>
              <td>${ev.get('fill',0):,.2f}</td>
              <td>${ev.get('tp',0) or 0:,.2f}</td>
              <td>${ev.get('sl',0) or 0:,.2f}</td>
              <td>—</td>
              <td>OPEN</td>
              <td class="{pnl_class}">RRR {ev.get('rrr',0):.2f}</td>
              <td style="color:var(--muted);font-size:0.75rem">{ev.get('strategy','')}</td>
            </tr>"""

    ret_val = p["total_return_pct"]
    html = HTML_TEMPLATE.format(
        run_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        n_bars=data["config"]["n_bars"],
        n_symbols=len(data["config"]["symbols"]),
        total_return=f"{ret_val:+.2f}",
        return_class=_color_class(ret_val),
        initial_capital=f"${p['initial_capital']:,.0f}",
        final_equity=f"${p['equity']:,.2f}",
        cash=f"${p['cash']:,.2f}",
        realized_pnl=_fmt_money(p["realized_pnl"]),
        realized_class=_color_class(p["realized_pnl"]),
        commission=f"${p['total_commission']:,.2f}",
        max_dd=f"{p['max_drawdown_pct']:.2f}",
        sharpe=f"{p['sharpe_ratio']:.3f}",
        win_rate=f"{p['win_rate_pct']:.1f}",
        winners=t.get("winners", "—"),
        losers=t.get("losers", "—"),
        profit_factor=f"{p['profit_factor']:.3f}",
        expectancy=f"${t.get('expectancy', 0):,.2f}",
        total_trades=p["total_trades"],
        tp_count=t.get("tp_hit_count", "—"),
        sl_count=t.get("sl_hit_count", "—"),
        rr_ratio=f"{abs(t.get('avg_win', 0) / t.get('avg_loss', -1)):.2f}" if t.get("avg_loss") else "—",
        avg_win=f"${t.get('avg_win', 0):,.2f}",
        avg_loss=f"${t.get('avg_loss', 0):,.2f}",
        strategy_html=strategy_html_rows,
        equity_json=json.dumps(equities),
        dd_json=json.dumps(dds),
        labels_json=json.dumps(labels),
        strat_pie_json=json.dumps(strat_pie),
        outcome_json=json.dumps({
            "labels": bucket_labels,
            "values": bucket_counts,
            "colors": outcome_colors,
        }),
        trade_rows=trade_rows_html,
    )

    with open(output_path, "w") as f:
        f.write(html)
    print(f"HTML report generated: {output_path}")


if __name__ == "__main__":
    import sys
    inp = sys.argv[1] if len(sys.argv) > 1 else "backtest_results.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "trading_report.html"
    generate_html_report(inp, out)
