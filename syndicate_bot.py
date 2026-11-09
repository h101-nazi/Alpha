import os
import requests
import pytz
import json
import csv
import time
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time
from lse import LSE

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LSE_API_KEY = os.environ.get("LSE_API_KEY")

# ==============================================================================
# 1. DISCORD TEST MESSAGE (Fires immediately every time the script runs)
# ==============================================================================
if WEBHOOK_URL:
    try:
        requests.post(WEBHOOK_URL, json={"content": "✅ **SYSTEM CHECK:** GitHub Action triggered successfully. Webhook is working."})
        print("Test message sent to Discord.")
    except Exception as e:
        print(f"Failed to send test message: {e}")
else:
    print("❌ ERROR: DISCORD_WEBHOOK_URL is not set in GitHub Secrets.")

est = pytz.timezone('US/Eastern')
now_est = datetime.now(est)
today = now_est.strftime("%Y-%m-%d")

# ==============================================================================
# 2. POWELL FAKEOUT SCANNER (Runs 10:10 AM - 11:30 AM EST)
# ==============================================================================
def run_powell():
    print("Running Powell Fakeout Scanner...")
    TICKERS = ['NQ=F', 'ES=F', 'YM=F', 'RTY=F']
    SYMBOL_NAMES = {'NQ=F': 'NAS100', 'ES=F': 'US500', 'YM=F': 'US30', 'RTY=F': 'US2000'}
    STATE_FILE = "powell_last_alert.json"
    JOURNAL_FILE = "powell_trade_journal.csv"
    
    def load_state():
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f: return json.load(f)
        return {}
    state = load_state()

    def journal_trade(ticker, direction, entry, stop, target):
        file_exists = os.path.isfile(JOURNAL_FILE)
        with open(JOURNAL_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Time_EST", "Ticker", "Direction", "Entry", "Stop_Loss", "Target_1.5R", "Result"])
            writer.writerow([today, now_est.strftime("%H:%M:%S"), ticker, direction, round(entry, 2), round(stop, 2), round(target, 2), "PENDING"])

    for ticker in TICKERS:
        try:
            df = yf.download(ticker, period='1d', interval='5m', progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df.index = df.index.tz_convert('America/New_York')
            
            df['TR'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
            df['ATR'] = df['TR'].rolling(window=14).mean()
            df['Vol_Avg'] = df['volume'].rolling(window=20).mean()
            
            range_window = df.between_time('09:50', '10:10')
            if len(range_window) < 4: continue
            range_high = range_window['high'].max()
            range_low = range_window['low'].min()
            
            post_10 = df[df.index.time > dt_time(10, 10)]
            
            for idx, row in post_10.iterrows():
                if state.get(ticker) == today: break
                is_short = (row['high'] > range_high and row['close'] < range_high)
                is_long = (row['low'] < range_low and row['close'] > range_low)
                vol_ok = row['volume'] > (row['Vol_Avg'] * 1.2)

                if (is_short or is_long) and vol_ok:
                    direction = "SHORT" if is_short else "LONG"
                    entry = row['close']
                    stop = (row['high'] + (row['ATR'] * 0.5)) if is_short else (row['low'] - (row['ATR'] * 0.5))
                    risk = abs(stop - entry)
                    target = entry - (risk * 1.5) if is_short else entry + (risk * 1.5)
                    
                    msg = f"🚨 **POWELL {direction}: {SYMBOL_NAMES[ticker]} (5m)** 🚨\nEntry: {entry:.2f} | Stop: {stop:.2f} | Target: {target:.2f}"
                    if WEBHOOK_URL: requests.post(WEBHOOK_URL, json={"content": msg})
                    journal_trade(SYMBOL_NAMES[ticker], direction, entry, stop, target)
                    state[ticker] = today
                    with open(STATE_FILE, "w") as f: json.dump(state, f)
                    break
        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

# ==============================================================================
# 3. GEX SCANNER (Runs 4:10 PM - 4:30 PM EST)
# ==============================================================================
def run_gex():
    print("Running GEX Scanner...")
    TICKERS = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD", "NFLX", "JPM", "GLD"]
    JOURNAL_FILE = "syndicate_gex_journal.csv"
    
    if not LSE_API_KEY:
        print("❌ LSE_API_KEY missing.")
        return
        
    client = LSE(api_key=LSE_API_KEY)
    signals_found = 0
    
    def journal_trade(ticker, action, entry, target, regime):
        file_exists = os.path.isfile(JOURNAL_FILE)
        with open(JOURNAL_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Time_EST", "Ticker", "Action", "Entry", "Target_5D", "Regime", "Result"])
            writer.writerow([today, now_est.strftime("%H:%M:%S"), ticker, action, round(entry, 2), round(target, 2), regime, "PENDING"])

    for ticker in TICKERS:
        try:
            chain = client.options(ticker, max_dte=30)
            if not chain: continue
            df = pd.DataFrame(chain).dropna(subset=['gamma', 'strike', 'volume_today'])
            df = df[df['volume_today'] > 0]
            if df.empty: continue
                
            spot = df['greeks_underlying_price'].iloc[0]
            df['gex'] = df['gamma'] * df['volume_today'] * 100 * (spot ** 2) * 0.01
            
            calls = df[df['contract_type'] == 'call']
            puts = df[df['contract_type'] == 'put']
            call_wall = calls.loc[calls['gex'].idxmax()]['strike'] if not calls.empty else spot
            put_wall = puts.loc[puts['gex'].idxmax()]['strike'] if not puts.empty else spot
            total_gex = calls['gex'].sum() - puts['gex'].sum()
            
            if total_gex > 0:
                dist_to_call = (call_wall - spot) / spot
                if -0.005 <= dist_to_call <= 0.005:
                    signals_found += 1
                    msg = f"🚨 **GEX SHORT: {ticker}** 🚨\nPositive Gamma. Touching Call Wall (${call_wall:.2f}).\nEntry: {spot:.2f}"
                    if WEBHOOK_URL: requests.post(WEBHOOK_URL, json={"content": msg})
                    journal_trade(ticker, "SHORT", spot, put_wall, "POSITIVE")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error {ticker}: {e}")
            
    if signals_found == 0:
        print("GEX Scan complete. No valid setups found.")

# ==============================================================================
# 4. EXECUTION LOGIC (Time Gates)
# ==============================================================================
print(f"Current EST Time: {now_est.strftime('%H:%M')}")

# Powell runs between 10:10 and 11:30 AM EST
if dt_time(10, 10) <= now_est.time() <= dt_time(11, 30):
    run_powell()
# GEX runs between 4:10 and 4:30 PM EST
elif dt_time(16, 10) <= now_est.time() <= dt_time(16, 30):
    run_gex()
else:
    print("Outside of trading windows. Sleeping.")
