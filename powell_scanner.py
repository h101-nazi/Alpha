import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import json
import csv
from datetime import datetime, time as dt_time
import pytz

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TICKERS = ['NQ=F', 'ES=F', 'YM=F', 'RTY=F']
SYMBOL_NAMES = {'NQ=F': 'NAS100', 'ES=F': 'US500', 'YM=F': 'US30', 'RTY=F': 'US2000'}
STATE_FILE = "powell_last_alert.json"
JOURNAL_FILE = "powell_trade_journal.csv"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def send_discord(msg):
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"content": msg})

def journal_trade(ticker, direction, entry, stop, target):
    file_exists = os.path.isfile(JOURNAL_FILE)
    with open(JOURNAL_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Time_EST", "Ticker", "Direction", "Entry", "Stop_Loss", "Target_1.5R", "Result"])
        
        est = pytz.timezone('US/Eastern')
        now = datetime.now(est)
        writer.writerow([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            ticker,
            direction,
            round(entry, 2),
            round(stop, 2),
            round(target, 2),
            "PENDING"
        ])

def scan_market():
    est = pytz.timezone('US/Eastern')
    now_est = datetime.now(est)
    
    # Print to GitHub logs
    print(f"Scanning at {now_est.strftime('%H:%M')} EST...")
    
    if not (dt_time(10, 10) <= now_est.time() <= dt_time(11, 30)):
        send_discord("⚙️ **Powell Scanner:** Woke up, but it is outside the 10:10 AM - 11:30 AM EST trading window. Sleeping.")
        print("Outside of trading window.")
        return
        
    state = load_state()
    today = now_est.strftime("%Y-%m-%d")
    trades_found = False
    scan_results = []

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
                if state.get(ticker) == today:
                    break

                is_short = (row['high'] > range_high and row['close'] < range_high)
                is_long = (row['low'] < range_low and row['close'] > range_low)
                vol_ok = row['volume'] > (row['Vol_Avg'] * 1.2)

                if (is_short or is_long) and vol_ok:
                    trades_found = True
                    direction = "SHORT" if is_short else "LONG"
                    entry = row['close']
                    stop = (row['high'] + (row['ATR'] * 0.5)) if is_short else (row['low'] - (row['ATR'] * 0.5))
                    risk = abs(stop - entry)
                    target = entry - (risk * 1.5) if is_short else entry + (risk * 1.5)
                    
                    msg = f"🚨 **{direction} SIGNAL: {SYMBOL_NAMES[ticker]} (5m)** 🚨\n"
                    msg += f"Fakeout Sweep on 10 AM Range.\n"
                    msg += f"**Entry:** {entry:.2f}\n"
                    msg += f"**Stop Loss:** {stop:.2f}\n"
                    msg += f"**Target (1.5R):** {target:.2f}"
                    
                    send_discord(msg)
                    journal_trade(SYMBOL_NAMES[ticker], direction, entry, stop, target)
                    
                    state[ticker] = today
                    save_state(state)
                    break

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

    if not trades_found:
        heartbeat = f"⚙️ **Powell Scanner Check:** Scanned {len(TICKERS)} tickers. No valid fakeout setups found at {now_est.strftime('%H:%M')} EST. Waiting for the next 5-min bar."
        send_discord(heartbeat)
        print(heartbeat)

if __name__ == "__main__":
    scan_market()
