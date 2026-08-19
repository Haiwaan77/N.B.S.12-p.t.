import json
from datetime import datetime

# डेटा लोड
try:
    with open('trades.json') as f:
        trades = json.load(f)
except:
    trades = []
try:
    with open('open_positions.json') as f:
        open_positions = json.load(f)
except:
    open_positions = []
try:
    with open('strategies.json') as f:
        all_strategies = json.load(f)
except:
    all_strategies = []

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

lines = []
lines.append("# 📊 Paper Trading Report")
lines.append(f"Generated at: {now}\n")

for strat in all_strategies:
    name = strat.get('name', 'Unknown')
    s_trades = [t for t in trades if t.get('strategy') == name]
    s_open = [p for p in open_positions if p.get('strategy') == name]

    total_closed = len(s_trades)
    total_open = len(s_open)
    total_pnl = sum(t.get('pnl', 0) for t in s_trades)
    wins = sum(1 for t in s_trades if t.get('pnl', 0) > 0)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

    lines.append(f"## {name}")
    lines.append(f"| Total Orders | Open Orders | Closed Orders | Total P&L (₹) | Win Rate |")
    lines.append(f"|--------------|-------------|---------------|---------------|----------|")
    lines.append(f"| {total_closed + total_open} | {total_open} | {total_closed} | {total_pnl:+.2f} | {win_rate:.1f}% |")
    lines.append("")

    if s_open:
        lines.append("### ⏳ Open Positions")
        lines.append("| Entry Time | Type | Strike | Entry Premium | SL | Trailing |")
        lines.append("|------------|------|--------|---------------|----|----------|")
        for p in s_open:
            lines.append(f"| {p.get('entry_time','')} | {p.get('type','')} | {p.get('strike','')} | {p.get('entry_premium','')} | {p.get('sl','')} | {'Yes' if p.get('trail_active') else 'No'} |")
        lines.append("")

    if s_trades:
        lines.append("### 📄 Closed Trades")
        lines.append("| Entry | Exit | Type | Entry Prem | Exit Prem | P&L (₹) | Exit Reason | SL Type |")
        lines.append("|-------|------|------|-----------|-----------|---------|-------------|---------|")
        for t in s_trades:
            lines.append(f"| {t.get('entry_time','')} | {t.get('exit_time','')} | {t.get('type','')} | {t.get('entry_premium','')} | {t.get('exit_premium','')} | {t.get('pnl',0):+.2f} | {t.get('exit_reason','')} | {t.get('sl_type','N/A')} |")
        lines.append("")

        profit = [t for t in s_trades if t.get('pnl',0) > 0]
        if profit:
            lines.append("### ✅ Profit Trades")
            lines.append("| Entry | Exit | P&L (₹) | Exit Reason |")
            lines.append("|-------|------|---------|-------------|")
            for t in profit:
                lines.append(f"| {t.get('entry_time','')} | {t.get('exit_time','')} | {t.get('pnl',0):+.2f} | {t.get('exit_reason','')} |")
            lines.append("")

        init_sl = [t for t in s_trades if t.get('exit_reason') == 'SL Hit' and t.get('sl_type') == 'initial']
        if init_sl:
            lines.append("### 🛑 Initial SL Hit")
            lines.append("| Entry | Exit | P&L (₹) |")
            lines.append("|-------|------|---------|")
            for t in init_sl:
                lines.append(f"| {t.get('entry_time','')} | {t.get('exit_time','')} | {t.get('pnl',0):+.2f} |")
            lines.append("")

        tr_sl = [t for t in s_trades if t.get('exit_reason') == 'SL Hit' and t.get('sl_type') == 'trailing']
        if tr_sl:
            lines.append("### 🔁 Trailing SL Hit")
            lines.append("| Entry | Exit | P&L (₹) |")
            lines.append("|-------|------|---------|")
            for t in tr_sl:
                lines.append(f"| {t.get('entry_time','')} | {t.get('exit_time','')} | {t.get('pnl',0):+.2f} |")
            lines.append("")

        loss = [t for t in s_trades if t.get('pnl',0) <= 0]
        if loss:
            lines.append("### ❌ Loss Trades")
            lines.append("| Entry | Exit | P&L (₹) | Exit Reason |")
            lines.append("|-------|------|---------|-------------|")
            for t in loss:
                lines.append(f"| {t.get('entry_time','')} | {t.get('exit_time','')} | {t.get('pnl',0):+.2f} | {t.get('exit_reason','')} |")
            lines.append("")

with open('report.md', 'w') as f:
    f.write("\n".join(lines))

print("Markdown report generated: report.md")
