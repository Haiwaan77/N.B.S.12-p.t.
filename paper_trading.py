import os
import json
import math
from datetime import datetime, timedelta, time as dt_time
from calendar import monthrange, THURSDAY
import pytz
import pandas as pd
import numpy as np
import yfinance as yf
from nsepython import nsefetch

IST = pytz.timezone('Asia/Kolkata')

# ---------- NSE Option Chain ----------
def get_nse_chain():
    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        return nsefetch(url)
    except Exception as e:
        print(f"NSE chain fetch error: {e}")
        return None

def get_spot_from_chain(chain):
    try:
        return float(chain['records']['underlyingValue'])
    except Exception:
        return None

def get_atm_strike(spot, step=50):
    return int(round(spot / step) * step)

def parse_expiry_date(date_str):
    try:
        return datetime.strptime(date_str, "%d-%b-%Y").date()
    except Exception:
        return None

def select_expiry_date(chain, mode, now):
    if not chain:
        return None
    expiry_strings = chain.get('records', {}).get('expiryDates', [])
    if not expiry_strings:
        return None
    dates = [parse_expiry_date(d) for d in expiry_strings]
    dates = [d for d in dates if d]
    if not dates:
        return expiry_strings[0]

    if mode == 'weekly' or mode == 'intraday':
        # अगला गुरुवार
        days_until_thu = (THURSDAY - now.weekday()) % 7
        if days_until_thu == 0:
            days_until_thu = 7
        target = (now + timedelta(days=days_until_thu)).date()
    elif mode == 'monthly':
        # महीने का आखिरी गुरुवार
        y, m = now.year, now.month
        last = monthrange(y, m)[1]
        d = datetime(y, m, last).date()
        while d.weekday() != THURSDAY:
            d -= timedelta(days=1)
        target = d
        if now.date() > target:
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
            last = monthrange(y, m)[1]
            d = datetime(y, m, last).date()
            while d.weekday() != THURSDAY:
                d -= timedelta(days=1)
            target = d
    else:
        target = dates[0]

    for d in dates:
        if d >= target:
            return d.strftime("%d-%b-%Y")
    return dates[-1].strftime("%d-%b-%Y")

def get_option_ltp(chain, expiry_date_str, strike, opt_type):
    try:
        for rec in chain['records']['data']:
            if rec['expiryDate'] == expiry_date_str and int(rec['strikePrice']) == int(strike):
                if opt_type == 'CE':
                    return float(rec['CE']['lastPrice'])
                else:
                    return float(rec['PE']['lastPrice'])
        return None
    except Exception as e:
        print(f"Option LTP error: {e}")
        return None

def get_oi_iv(chain, expiry_date_str, strike, opt_type):
    try:
        for rec in chain['records']['data']:
            if rec['expiryDate'] == expiry_date_str and int(rec['strikePrice']) == int(strike):
                if opt_type == 'CE':
                    return int(rec['CE'].get('openInterest', 0)), float(rec['CE'].get('impliedVolatility', 0))
                else:
                    return int(rec['PE'].get('openInterest', 0)), float(rec['PE'].get('impliedVolatility', 0))
    except Exception:
        pass
    return 0, 0.0

# ---------- हिस्टोरिकल कैंडल डेटा ----------
def fetch_candles(timeframe, period_days):
    interval_map = {'15m': '15m', '30m': '30m', '1h': '1h', '1d': '1d'}
    interval = interval_map.get(timeframe, '1h')
    end = datetime.now(IST)
    start = end - timedelta(days=period_days)
    df = yf.download('^NSEI', start=start, end=end, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)
    return df

def calculate_indicators(df, rsi_type='ewm'):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    if rsi_type == 'sma':
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
    else:
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['macd_above'] = df['macd'] > df['signal']
    df['cross_up'] = df['macd_above'] & ~df['macd_above'].shift(1).fillna(False)
    df['cross_down'] = (~df['macd_above']) & df['macd_above'].shift(1).fillna(False)
    return df

# ---------- मुख्य बॉट ----------
def run_bot():
    print("NSE Option Chain data fetch हो रहा है...")
    chain = get_nse_chain()
    if not chain:
        print("NSE data unavailable")
        return

    spot = get_spot_from_chain(chain)
    if spot is None:
        print("Spot price unavailable")
        return
    print(f"Spot Price: {spot}")

    now = datetime.now(IST)

    # पुरानी स्थितियाँ लोड करें
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

    strategies = []
    try:
        with open('strategies.json') as f:
            strategies = json.load(f)
    except Exception:
        print("strategies.json not found")
        return

    for strat in strategies:
        name = strat['name']
        timeframe = strat['timeframe']
        period_raw = str(strat.get('period', '60d'))
        if 'y' in period_raw:
            period_days = int(period_raw.replace('y', '')) * 365
        else:
            period_days = int(period_raw.replace('d', ''))
        # yfinance limits
        if timeframe in ['15m', '30m']:
            period_days = min(period_days, 59)

        df = fetch_candles(timeframe, period_days)
        if df is None or len(df) < 30:
            print(f"{name}: insufficient data")
            continue
        df = calculate_indicators(df, strat['rsi_type'])

        exit_mode = strat['exit_mode']
        rsi_above = strat['rsi_cross_above']
        rsi_below = strat['rsi_cross_below']
        trail_pct = strat['trail_pct']
        lot_size = strat['lot_size']
        use_macd_exit = strat.get('use_macd_exit', False)

        expiry_date_str = select_expiry_date(chain, exit_mode, now)
        if expiry_date_str is None:
            print(f"{name}: expiry not available")
            continue

        # क्या इस रणनीति की कोई खुली पोज़ीशन है?
        open_pos = None
        for pos in open_positions:
            if pos['strategy'] == name:
                open_pos = pos
                break

        if open_pos:
            # ---------- एग्जिट जाँच ----------
            opt_type = 'CE' if open_pos['type'] == 'CALL' else 'PE'
            exit_premium = get_option_ltp(chain, open_pos['expiry_date'], open_pos['strike'], opt_type)
            if exit_premium is None:
                print(f"{name}: option ltp not available, exit skipped")
                continue

            exit_triggered = False
            exit_reason = ''

            # समय-सीमा एग्जिट
            if exit_mode == 'intraday':
                day_end = now.replace(hour=15, minute=15, second=0, microsecond=0)
                if now >= day_end:
                    exit_triggered = True
                    exit_reason = 'Intraday Exit'
            else:
                expiry_d = parse_expiry_date(open_pos['expiry_date'])
                if expiry_d:
                    market_close = dt_time(15, 15)
                    if now.date() > expiry_d or (now.date() == expiry_d and now.time() >= market_close):
                        exit_triggered = True
                        exit_reason = f'{exit_mode.capitalize()} Exit'

            # MACD विपरीत क्रॉस (केवल डेली SMA)
            if not exit_triggered and use_macd_exit:
                if len(df) >= 2:
                    last_cross_down = bool(df['cross_down'].iloc[-2])
                    last_cross_up = bool(df['cross_up'].iloc[-2])
                    if open_pos['type'] == 'CALL' and last_cross_down:
                        exit_triggered = True
                        exit_reason = 'MACD Cross Down'
                    elif open_pos['type'] == 'PUT' and last_cross_up:
                        exit_triggered = True
                        exit_reason = 'MACD Cross Up'

            # ट्रेलिंग SL एक्टिवेशन
            if not exit_triggered:
                if not open_pos['trail_active']:
                    if open_pos['type'] == 'CALL' and spot >= open_pos['entry_spot'] * (1 + trail_pct / 100):
                        open_pos['trail_active'] = True
                    elif open_pos['type'] == 'PUT' and spot <= open_pos['entry_spot'] * (1 - trail_pct / 100):
                        open_pos['trail_active'] = True

                # SL अपडेट
                if open_pos['trail_active'] and len(df) >= 3:
                    prev1 = df.iloc[-2]
                    prev2 = df.iloc[-3]
                    if open_pos['type'] == 'CALL':
                        new_sl = min(prev1['low'], prev2['low'])
                        if new_sl > open_pos['sl']:
                            open_pos['sl'] = new_sl
                    else:
                        new_sl = max(prev1['high'], prev2['high'])
                        if new_sl < open_pos['sl']:
                            open_pos['sl'] = new_sl

                # SL हिट चेक
                if open_pos['type'] == 'CALL' and spot <= open_pos['sl']:
                    exit_triggered = True
                    exit_reason = 'SL Hit'
                elif open_pos['type'] == 'PUT' and spot >= open_pos['sl']:
                    exit_triggered = True
                    exit_reason = 'SL Hit'

            if exit_triggered:
                pnl = (exit_premium - open_pos['entry_premium']) * lot_size
                trades.append({
                    'strategy': name,
                    'entry_time': open_pos['entry_time'],
                    'exit_time': str(now),
                    'type': open_pos['type'],
                    'strike': open_pos['strike'],
                    'entry_premium': open_pos['entry_premium'],
                    'exit_premium': exit_premium,
                    'exit_reason': exit_reason,
                    'pnl': round(pnl, 2)
                })
                # पोज़ीशन हटाएँ
                open_positions = [p for p in open_positions if p['strategy'] != name]
                print(f"{name}: {exit_reason} | P&L: {pnl:.2f}")
        else:
            # ---------- नया सिग्नल ----------
            if len(df) >= 3:
                signal_bar = df.iloc[-2]
                current_bar = df.iloc[-1]
                trade_type = None
                sl = 0.0

                if bool(signal_bar['cross_up']) and float(signal_bar['rsi']) < rsi_above:
                    trade_type = 'CALL'
                    sl = float(signal_bar['low'])
                elif bool(signal_bar['cross_down']) and float(signal_bar['rsi']) > rsi_below:
                    trade_type = 'PUT'
                    sl = float(signal_bar['high'])

                if trade_type:
                    strike = get_atm_strike(spot)
                    opt_type = 'CE' if trade_type == 'CALL' else 'PE'
                    entry_premium = get_option_ltp(chain, expiry_date_str, strike, opt_type)
                    if entry_premium:
                        oi, iv = get_oi_iv(chain, expiry_date_str, strike, opt_type)
                        open_positions.append({
                            'strategy': name,
                            'type': trade_type,
                            'strike': strike,
                            'entry_spot': spot,
                            'entry_premium': entry_premium,
                            'sl': sl,
                            'trail_active': False,
                            'entry_time': str(now),
                            'expiry_date': expiry_date_str,
                            'oi_at_entry': oi,
                            'iv_at_entry': iv
                        })
                        print(f"{name}: Entered {trade_type} at premium {entry_premium}, SL: {sl}")

    # फाइलों में सेव करें
    with open('trades.json', 'w') as f:
        json.dump(trades, f, indent=2)
    with open('open_positions.json', 'w') as f:
        json.dump(open_positions, f, indent=2)
    print("Bot run completed.")

if __name__ == '__main__':
    run_bot()
