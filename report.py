import json
from datetime import datetime

# ---------- डेटा लोड ----------
try:
    with open('trades.json') as f:
        trades = json.load(f)
except Exception:
    trades = []

try:
    with open('open_positions.json') as f:
        open_positions = json.load(f)
except Exception:
    open_positions = []

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# सभी strategy निकालें
strategies = set()
for t in trades:
    strategies.add(t.get('strategy', 'Unknown'))
for p in open_positions:
    strategies.add(p.get('strategy', 'Unknown'))

# ---------- HTML शुरू ----------
html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Paper Trading Report</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 10px; background: #fafafa; }}
        h1 {{ color: #2c3e50; }}
        .strategy {{ border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; padding: 10px; background: #fff; }}
        .summary {{ background: #f0f4f8; padding: 10px; border-radius: 5px; margin-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: 13px; }}
        th, td {{ padding: 6px; border-bottom: 1px solid #ddd; text-align: left; }}
        th {{ background: #e0e0e0; }}
        .profit {{ color: green; font-weight: bold; }}
        .loss {{ color: red; font-weight: bold; }}
        h3 {{ margin: 10px 0 5px 0; color: #34495e; }}
    </style>
</head>
<body>
<h1>📊 Paper Trading Report</h1>
<p>Generated at: {now}</p>
"""

# ---------- हर strategy के लिए ----------
for strat in sorted(strategies):
    strat_trades = [t for t in trades if t.get('strategy') == strat]
    strat_open = [p for p in open_positions if p.get('strategy') == strat]

    total_closed = len(strat_trades)
    total_open = len(strat_open)
    win_count = sum(1 for t in strat_trades if t.get('pnl', 0) > 0)
    total_pnl = sum(t.get('pnl', 0) for t in strat_trades)
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0

    html += f"<div class='strategy'><h2>{strat}</h2>"
    html += "<div class='summary'>"
    html += f"<b>Total Orders:</b> {total_closed + total_open} &nbsp;|&nbsp; "
    html += f"<b>Open Orders:</b> {total_open} &nbsp;|&nbsp; "
    html += f"<b>Closed Orders:</b> {total_closed} &nbsp;|&nbsp; "
    html += f"<b>Total P&L:</b> <span class='{'profit' if total_pnl >= 0 else 'loss'}'>{total_pnl:+.2f}</span> &nbsp;|&nbsp; "
    html += f"<b>Win Rate:</b> {win_rate:.1f}%"
    html += "</div>"

    # Open Positions
    if strat_open:
        html += "<h3>⏳ Open Positions</h3>"
        html += "<table><tr><th>Entry Time</th><th>Type</th><th>Strike</th><th>Entry Premium</th><th>SL</th><th>Trailing Active</th></tr>"
        for p in strat_open:
            trailing = 'Yes' if p.get('trail_active', False) else 'No'
            html += f"<tr><td>{p.get('entry_time','')}</td><td>{p.get('type','')}</td><td>{p.get('strike','')}</td><td>{p.get('entry_premium','')}</td><td>{p.get('sl','')}</td><td>{trailing}</td></tr>"
        html += "</table>"

    # Closed Trades
    if strat_trades:
        html += "<h3>📄 Closed Trades (All)</h3>"
        html += "<table><tr><th>Entry</th><th>Exit</th><th>Type</th><th>Entry Prem</th><th>Exit Prem</th><th>P&L</th><th>Exit Reason</th><th>SL Type</th></tr>"
        for t in strat_trades:
            sl_type = t.get('sl_type', 'N/A')
            pnl = t.get('pnl', 0)
            pnl_class = 'profit' if pnl > 0 else 'loss'
            html += f"<tr><td>{t.get('entry_time','')}</td><td>{t.get('exit_time','')}</td><td>{t.get('type','')}</td><td>{t.get('entry_premium','')}</td><td>{t.get('exit_premium','')}</td><td class='{pnl_class}'>{pnl:+.2f}</td><td>{t.get('exit_reason','')}</td><td>{sl_type}</td></tr>"
        html += "</table>"

        # Profit Trades
        profit_trades = [t for t in strat_trades if t.get('pnl', 0) > 0]
        if profit_trades:
            html += "<h3>✅ Profit Trades</h3>"
            html += "<table><tr><th>Entry</th><th>Exit</th><th>P&L</th><th>Exit Reason</th></tr>"
            for t in profit_trades:
                html += f"<tr><td>{t.get('entry_time','')}</td><td>{t.get('exit_time','')}</td><td class='profit'>{t.get('pnl',0):+.2f}</td><td>{t.get('exit_reason','')}</td></tr>"
            html += "</table>"

        # Initial SL Hit Trades
        initial_sl = [t for t in strat_trades if t.get('exit_reason') == 'SL Hit' and t.get('sl_type') == 'initial']
        if initial_sl:
            html += "<h3>🛑 Initial SL Hit Trades</h3>"
            html += "<table><tr><th>Entry</th><th>Exit</th><th>P&L</th></tr>"
            for t in initial_sl:
                html += f"<tr><td>{t.get('entry_time','')}</td><td>{t.get('exit_time','')}</td><td class='loss'>{t.get('pnl',0):+.2f}</td></tr>"
            html += "</table>"

        # Trailing SL Hit Trades
        trailing_sl = [t for t in strat_trades if t.get('exit_reason') == 'SL Hit' and t.get('sl_type') == 'trailing']
        if trailing_sl:
            html += "<h3>🔁 Trailing SL Hit Trades</h3>"
            html += "<table><tr><th>Entry</th><th>Exit</th><th>P&L</th></tr>"
            for t in trailing_sl:
                pnl = t.get('pnl', 0)
                pnl_class = 'profit' if pnl >= 0 else 'loss'
                html += f"<tr><td>{t.get('entry_time','')}</td><td>{t.get('exit_time','')}</td><td class='{pnl_class}'>{pnl:+.2f}</td></tr>"
            html += "</table>"

        # Loss Trades (all negative)
        loss_trades = [t for t in strat_trades if t.get('pnl', 0) <= 0]
        if loss_trades:
            html += "<h3>❌ Loss Trades</h3>"
            html += "<table><tr><th>Entry</th><th>Exit</th><th>P&L</th><th>Exit Reason</th></tr>"
            for t in loss_trades:
                html += f"<tr><td>{t.get('entry_time','')}</td><td>{t.get('exit_time','')}</td><td class='loss'>{t.get('pnl',0):+.2f}</td><td>{t.get('exit_reason','')}</td></tr>"
            html += "</table>"

    html += "</div>"

html += "</body></html>"

# ---------- रिपोर्ट फाइल लिखें ----------
with open('report.html', 'w') as f:
    f.write(html)

print("Report generated: report.html")
