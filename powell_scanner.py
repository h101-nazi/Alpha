import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import json
import csv
from datetime import datetime, time as dt_time
import pytz

WEBHOOK_URL = os.environ.get("https://discord.com/api/webhooks/1569276489071984726/_LnpEoz9Eu6AYJh1vOu6alasfq_H4LrSLXHr0FsO9Xm8o0ZwvmY5mHLm0XLQs1RBxZYM")
TICKERS = ['NQ=F', 'ES=F', 'YM=F', 'RTY=F']
SYMBOL_NAMES = {'NQ=F': 'NAS100', 'ES=F': 'US500', 'YM=F': 'US30', 'RTY=F': 'US2000'}
STATE_FILE = "last_alert.json"
JOURNAL_FILE = "powell_trade_journal.csv"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

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
    
    # Run scanner right after the 10 AM candle closes
    if not (dt_time(11, 0) <= now_est.time() <= dt_time(12, 0)):
        print("Outside of 1H trading window. Skipping.")
        return
        
    print(f"Scanning 1H data at {now_est.strftime('%H:%M')} EST...")
    state = load_state()
    today = now_est.strftime("%Y-%m-%d")

    for ticker in TICKERS:
        try:
            # FETCHING 1-HOUR DATA NOW
            df = yf.download(ticker, period='1mo', interval='1h', progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df.index = df.index.tz_convert('America/New_York')
            
            df['SMA_200'] = df['close'].rolling(window=200).mean()
            df['Typical'] = (df['high'] + df['low'] + df['close']) / 3
            df['VWAP'] = (df['Typical'] * df['volume']).cumsum() / df['volume'].cumsum()
            df['TR'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
            df['ATR'] = df['TR'].rolling(window=14).mean()
            
            # The 10 AM candle is the only one we care about for the range
            range_window = df.between_time('10:00', '10:00')
            if len(range_window) < 1: continue
            range_high = range_window['high'].max()
            range_low = range_window['low'].min()
            
            # Check the 11 AM candle for the fakeout
            post_10 = df[df.index.time >= dt_time(11, 0)]
            
            for idx, row in post_10.iterrows():
                if state.get(ticker) == today:
                    break

                is_short = (row['high'] > range_high and row['close'] < range_high)
                is_long = (row['low'] < range_low and row['close'] > range_low)

                if is_short or is_long:
                    direction = "SHORT" if is_short else "LONG"
                    entry = row['close']
                    stop = (row['high'] + (row['ATR'] * 0.5)) if is_short else (row['low'] - (row['ATR'] * 0.5))
                    risk = abs(stop - entry)
                    target = entry - (risk * 1.5) if is_short else entry + (risk * 1.5)
                    
                    msg = f"🚨 **{direction} SIGNAL: {SYMBOL_NAMES[ticker]} (1H)** 🚨\n"
                    msg += f"Fakeout Sweep on 10 AM Range.\n"
                    msg += f"**Entry:** {entry:.2f}\n"
                    msg += f"**Stop Loss:** {stop:.2f}\n"
                    msg += f"**Target (1.5R):** {target:.2f}"
                    
                    if WEBHOOK_URL:
                        requests.post(WEBHOOK_URL, json={"content": msg})
                        print(f"Alert sent for {ticker}")
                    
                    journal_trade(SYMBOL_NAMES[ticker], direction, entry, stop, target)
                    print(f"Logged {ticker} to journal.")
                    
                    state[ticker] = today
                    save_state(state)
                    break

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

if __name__ == "__main__":
    scan_market()
