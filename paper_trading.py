import os
import json
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
try:
    from SmartApi import SmartConnect
except ImportError:
    from smartapi import SmartConnect
from calendar import monthrange, THURSDAY
import math

IST = pytz.timezone('Asia/Kolkata')

# ---------- Angel One SmartAPI लॉगिन ----------
def angel_login():
    api_key = os.environ.get('ANGEL_API_KEY')
    client_id = os.environ.get('ANGEL_CLIENT_ID')
    password = os.environ.get('ANGEL_PASSWORD')
    totp = ""   # 2FA बंद है, इसलिए खाली

    obj = SmartConnect(api_key=api_key)
    data = obj.generateSession(client_id, password, totp)
    if data.get('status'):
        jwt_token = data['data']['jwtToken']
        refresh_token = data['data']['refreshToken']
        return obj, jwt_token, refresh_token
    else:
        raise Exception("Angel Login Failed")

# ---------- एक्सपायरी हेल्पर ----------
def next_weekly_expiry(date):
    days_until_thu = (THURSDAY - date.weekday()) % 7
    if days_until_thu == 0:
        days_until_thu = 7
    return date + timedelta(days=days_until_thu)

def next_monthly_expiry(date):
    y, m = date.year, date.month
    last_day = monthrange(y, m)[1]
    d = datetime(y, m, last_day)
    while d.weekday() != THURSDAY:
        d -= timedelta(days=1)
    expiry = d.date()
    if date.date() > expiry:
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
        last_day = monthrange(y, m)[1]
        d = datetime(y, m, last_day)
        while d.weekday() != THURSDAY:
            d -= timedelta(days=1)
        expiry = d.date()
    return expiry

# ---------- ATM स्ट्राइक ----------
def get_atm_strike(spot_price, step=50):
    return round(spot_price / step) * step

# ---------- इंडिकेटर गणना ----------
def calculate_indicators(df, rsi_type='ewm'):
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # RSI
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

    # क्रॉस
    df['macd_above'] = df['macd'] > df['signal']
    df['cross_up'] = df['macd_above'] & ~df['macd_above'].shift(1).fillna(False)
    df['cross_down'] = (~df['macd_above']) & df['macd_above'].shift(1).fillna(False)
    return df

# ---------- हिस्टोरिकल कैंडल डेटा लाना ----------
def fetch_candles(smart_obj, jwt_token, timeframe, days):
    """Angel One से हिस्टोरिकल कैंडल डेटा"""
    to_date = datetime.now(IST)
    from_date = to_date - timedelta(days=days)
    interval_map = {
        '1m': 'ONE_MINUTE',
        '5m': 'FIVE_MINUTE',
        '15m': 'FIFTEEN_MINUTE',
        '30m': 'THIRTY_MINUTE',
        '1h': 'ONE_HOUR',
        '1d': 'ONE_DAY'
    }
    interval = interval_map.get(timeframe, 'ONE_HOUR')
    try:
        # Angel One SmartAPI getCandleData का उपयोग करें
        # Param: exchange, symbol, interval, fromdate, todate (YYYY-MM-DD HH:MM)
        res = smart_obj.getCandleData(
            exchange="NSE",
            symbol="NIFTY",
            interval=interval,
            fromdate=from_date.strftime('%Y-%m-%d %H:%M'),
            todate=to_date.strftime('%Y-%m-%d %H:%M')
        )
        if res and 'data' in res and res['data']:
            df = pd.DataFrame(res['data'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_convert(IST)
            df.set_index('timestamp', inplace=True)
            df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
        return None
    except Exception as e:
        print(f"Candle fetch error: {e}")
        return None

# ---------- लाइव स्पॉट प्राइस ----------
def get_spot_price(smart_obj):
    try:
        res = smart_obj.ltp("NSE", "NIFTY", "")
        if res and 'data' in res:
            return float(res['data']['ltp'])
        return None
    except Exception as e:
        print(f"Spot price error: {e}")
        return None

# ---------- ऑप्शन LTP ----------
def get_option_ltp(smart_obj, expiry_date, strike, option_type):
    """option_type: 'CE' या 'PE'"""
    date_str = expiry_date.strftime('%y%m%d')
    symbol = f"NIFTY{date_str}{strike}{option_type}"
    try:
        res = smart_obj.ltp("NFO", symbol, "")
        if res and 'data' in res:
            return float(res['data']['ltp'])
        return None
    except Exception as e:
        print(f"Option LTP error for {symbol}: {e}")
        return None

# ---------- मुख्य बॉट ----------
def run_bot():
    # Angel लॉगिन
    try:
        smart_obj, jwt_token, refresh_token = angel_login()
        print("Angel One login successful")
    except Exception as e:
        print(f"Login error: {e}")
        return

    # पिछली स्थितियाँ
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

    # स्ट्रैटेजी लोड करें
    strategies = json.load(open('strategies.json'))

    # स्पॉट प्राइस
    spot_price = get_spot_price(smart_obj)
    if not spot_price:
        print("Spot price not available")
        return
    print(f"Spot Price: {spot_price}")

    now = datetime.now(IST)

    for strat in strategies:
        name = strat['name']
        timeframe = strat['timeframe']
        rsi_type = strat['rsi_type']
        rsi_above = strat['rsi_cross_above']
        rsi_below = strat['rsi_cross_below']
        trail_pct = strat['trail_pct']
        exit_mode = strat['exit_mode']
        use_macd_exit = strat.get('use_macd_exit', False)
        lot_size = strat['lot_size']

        # हिस्टोरिकल कैंडल डेटा लाओ (60 दिनों का काफी होगा)
        df = fetch_candles(smart_obj, jwt_token, timeframe, 60)
        if df is None or len(df) < 30:
            print(f"{name}: insufficient candle data")
            continue

        # इंडिकेटर जोड़ें
        df = calculate_indicators(df, rsi_type)

        # एक्सपायरी तय करें
        if exit_mode == 'weekly':
            expiry_date = next_weekly_expiry(now)
        else:
            expiry_date = next_monthly_expiry(now)

        # ATM स्ट्राइक
        atm_strike = get_atm_strike(spot_price)

        # क्या इस रणनीति के लिए कोई खुली पोज़ीशन है?
        open_pos = None
        for pos in open_positions:
            if pos['strategy'] == name:
                open_pos = pos
                break

        # ---------- ओपन पोज़ीशन मैनेज करें ----------
        if open_pos:
            option_type = "CE" if open_pos['type'] == 'CALL' else "PE"
            # वर्तमान ऑप्शन LTP
            option_ltp = get_option_ltp(smart_obj, expiry_date, atm_strike, option_type)
            if option_ltp is None:
                continue

            exit_triggered = False
            exit_premium = None
            exit_reason = ''

            # समय-सीमा एग्जिट
            if exit_mode == 'intraday':
                day_end = now.replace(hour=15, minute=15, second=0, microsecond=0)
                if now >= day_end:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'Intraday Exit'
            elif exit_mode == 'weekly':
                if now.date() >= expiry_date:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'Weekly Expiry'
            elif exit_mode == 'monthly':
                if now.date() >= expiry_date:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'Monthly Expiry'

            # MACD विपरीत क्रॉस (केवल डेली SMA)
            if not exit_triggered and use_macd_exit:
                last_cross_down = df['cross_down'].iloc[-1] if len(df) else False
                last_cross_up = df['cross_up'].iloc[-1] if len(df) else False
                if open_pos['type'] == 'CALL' and last_cross_down:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'MACD Cross Down'
                elif open_pos['type'] == 'PUT' and last_cross_up:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'MACD Cross Up'

            # SL / ट्रेलिंग SL (स्पॉट आधारित)
            if not exit_triggered:
                # ट्रेलिंग एक्टिवेशन
                if not open_pos['trail_active']:
                    if open_pos['type'] == 'CALL' and spot_price >= open_pos['entry_spot'] * (1 + trail_pct/100):
                        open_pos['trail_active'] = True
                    elif open_pos['type'] == 'PUT' and spot_price <= open_pos['entry_spot'] * (1 - trail_pct/100):
                        open_pos['trail_active'] = True

                # SL अपडेट (पिछले 2 कैंडल्स)
                if open_pos['trail_active']:
                    if len(df) >= 2:
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

                # SL चेक
                if open_pos['type'] == 'CALL' and spot_price <= open_pos['sl']:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'SL Hit'
                elif open_pos['type'] == 'PUT' and spot_price >= open_pos['sl']:
                    exit_triggered = True
                    exit_premium = option_ltp
                    exit_reason = 'SL Hit'

            if exit_triggered and exit_premium is not None:
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
                print(f"{name}: Exited {open_pos['type']} at premium {exit_premium}, P&L: {pnl}")

        # ---------- नया सिग्नल ----------
        else:
            # अंतिम कैंडल सिग्नल के लिए
            if len(df) >= 2:
                sig_idx = df.index[-2]  # सिग्नल कैंडल (पिछला)
                entry_idx = df.index[-1] # एंट्री कैंडल (वर्तमान)

                if df['cross_up'].iloc[-2] and df['rsi'].iloc[-2] < rsi_above:
                    # CALL सिग्नल
                    option_type = "CE"
                    entry_premium = get_option_ltp(smart_obj, expiry_date, atm_strike, option_type)
                    if entry_premium:
                        sl = df['low'].iloc[-2]  # सिग्नल कैंडल का लो
                        open_positions.append({
                            'strategy': name,
                            'type': 'CALL',
                            'strike': atm_strike,
                            'entry_spot': spot_price,
                            'entry_premium': entry_premium,
                            'sl': sl,
                            'trail_active': False,
                            'entry_time': str(now)
                        })
                        print(f"{name}: Entered CALL at premium {entry_premium}, SL: {sl}")
                elif df['cross_down'].iloc[-2] and df['rsi'].iloc[-2] > rsi_below:
                    # PUT सिग्नल
                    option_type = "PE"
                    entry_premium = get_option_ltp(smart_obj, expiry_date, atm_strike, option_type)
                    if entry_premium:
                        sl = df['high'].iloc[-2]  # सिग्नल कैंडल का हाई
                        open_positions.append({
                            'strategy': name,
                            'type': 'PUT',
                            'strike': atm_strike,
                            'entry_spot': spot_price,
                            'entry_premium': entry_premium,
                            'sl': sl,
                            'trail_active': False,
                            'entry_time': str(now)
                        })
                        print(f"{name}: Entered PUT at premium {entry_premium}, SL: {sl}")

    # फाइलों में सेव करें
    with open('trades.json', 'w') as f:
        json.dump(trades, f, indent=2)
    with open('open_positions.json', 'w') as f:
        json.dump(open_positions, f, indent=2)

if __name__ == '__main__':
    run_bot()
