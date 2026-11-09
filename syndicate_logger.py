import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from scipy.stats import norm
import os

def bs_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0: return 0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

def log_gex(tickers=["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]):
    out_file = "syndicate_gex_history.csv"
    rows = []
    now = datetime.now()
    
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if hist.empty: continue
            spot = hist["Close"].iloc[-1]
            
            exps = t.options
            if not exps: continue
            exp = exps[0]
            opt = t.option_chain(exp)
            
            exp_date = pd.to_datetime(exp).tz_localize("UTC")
            T = (exp_date - pd.Timestamp.now(tz="UTC")).total_seconds() / (365.25 * 24 * 3600)
            if T <= 0: continue
            
            call_gex, put_gex = 0, 0
            max_pain_calls, max_pain_puts = {}, {}
            total_call_oi, total_put_oi = 0, 0
            atm_iv = 0
            
            # Find ATM Strike
            strikes = opt.calls['strike'].values
            atm_strike = strikes[np.argmin(np.abs(strikes - spot))]
            
            for _, row in opt.calls.iterrows():
                total_call_oi += row["openInterest"]
                if row["strike"] == atm_strike:
                    atm_iv = row["impliedVolatility"] * 100 # Convert to percentage
                    
                if row["openInterest"] > 0 and row["impliedVolatility"] > 0:
                    g = bs_gamma(spot, row["strike"], T, 0.05, row["impliedVolatility"])
                    call_gex += g * row["openInterest"] * 100 * spot
                    max_pain_calls[row["strike"]] = row["openInterest"]
                    
            for _, row in opt.puts.iterrows():
                total_put_oi += row["openInterest"]
                if row["openInterest"] > 0 and row["impliedVolatility"] > 0:
                    g = bs_gamma(spot, row["strike"], T, 0.05, row["impliedVolatility"])
                    put_gex -= g * row["openInterest"] * 100 * spot
                    max_pain_puts[row["strike"]] = row["openInterest"]
                    
            total_gex = call_gex + put_gex
            call_wall = max(max_pain_calls, key=max_pain_calls.get) if max_pain_calls else spot
            put_wall = max(max_pain_puts, key=max_pain_puts.get) if max_pain_puts else spot
            
            # Calculate PCR
            pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 0
            
            rows.append({
                "Date": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Ticker": ticker,
                "Spot": spot,
                "Total_GEX": total_gex,
                "Call_Wall": call_wall,
                "Put_Wall": put_wall,
                "ATM_IV": atm_iv,
                "PCR_OI": pcr_oi
            })
            print(f"✅ Logged {ticker}")
        except Exception as e:
            print(f"❌ Failed {ticker}: {e}")
            
    if rows:
        df = pd.DataFrame(rows)
        # If file exists, align columns
        if os.path.exists(out_file):
            existing_df = pd.read_csv(out_file)
            df = pd.concat([existing_df, df], ignore_index=True)
            df.to_csv(out_file, index=False)
        else:
            df.to_csv(out_file, index=False)
        print("✅ Saved to CSV")

if __name__ == "__main__":
    log_gex()
