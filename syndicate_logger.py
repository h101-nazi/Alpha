import pandas as pd
import numpy as np
import requests
import os
import csv
import time
from datetime import datetime
import pytz
from lse import LSE

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LSE_API_KEY = os.environ.get("LSE_API_KEY")

TICKERS = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "TSLA", 
           "AMZN", "META", "GOOGL", "AMD", "NFLX", "JPM", "GLD"]
JOURNAL_FILE = "syndicate_gex_journal.csv"

client = LSE(api_key=LSE_API_KEY)

def journal_trade(ticker, action, entry, target, regime):
    file_exists = os.path.isfile(JOURNAL_FILE)
    with open(JOURNAL_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Time_EST", "Ticker", "Action", "Entry", "Target_5D", "Regime", "Result"])
        
        est = pytz.timezone('US/Eastern')
        now = datetime.now(est)
        writer.writerow([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            ticker,
            action,
            round(entry, 2),
            round(target, 2),
            regime,
            "PENDING"
        ])

def scan_gex():
    print("Scanning GEX for all tickers...")
    
    for ticker in TICKERS:
        try:
            chain = client.options(ticker, max_dte=30)
            if not chain: continue
                
            df = pd.DataFrame(chain)
            df = df.dropna(subset=['gamma', 'strike', 'volume_today'])
            df = df[df['volume_today'] > 0]
            
            if df.empty: continue
                
            spot = df['greeks_underlying_price'].iloc[0]
            
            df['gex'] = df['gamma'] * df['volume_today'] * 100 * (spot ** 2) * 0.01
            calls = df[df['contract_type'] == 'call']
            puts = df[df['contract_type'] == 'put']
            
            call_wall = calls.loc[calls['gex'].idxmax()]['strike'] if not calls.empty else spot
            put_wall = puts.loc[puts['gex'].idxmax()]['strike'] if not puts.empty else spot
            
            total_gex = calls['gex'].sum() - puts['gex'].sum()
            
            # --- THE GEX CALL WALL EDGE ---
            # If Positive Gamma AND spot is within 0.5% of Call Wall -> SHORT
            if total_gex > 0:
                dist_to_call = (call_wall - spot) / spot
                
                if -0.005 <= dist_to_call <= 0.005:
                    msg = f"🚨 **GEX SHORT SIGNAL: {ticker}** 🚨\n"
                    msg += f"Positive Gamma Regime. Price is touching the Call Wall.\n"
                    msg += f"**Entry:** {spot:.2f}\n"
                    msg += f"**Call Wall (Target):** {call_wall:.2f}\n"
                    msg += f"**Hold:** 5 Days"
                    
                    if WEBHOOK_URL:
                        requests.post(WEBHOOK_URL, json={"content": msg})
                    
                    journal_trade(ticker, "SHORT", spot, put_wall, "POSITIVE")
                    print(f"✅ Logged SHORT signal for {ticker}")
                    
            time.sleep(0.5)
                
        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

if __name__ == "__main__":
    scan_gex()
