import os, json, time, shutil, tempfile, subprocess, sys, traceback
import requests, importlib.util
# from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Markdown, display
from settings import tiingo_api, RAW, PRIVATE, ROOT, WS

TICKERS = ["SPY","QQQ","IWM","XLE","XLF","XLK","XLV","XLP","XLY"]
START, END = "2004-01-01", "2025-12-31"

def fetch_tiingo(symbol: str, start: str = START, end: str = END):
    """Fetch daily data from Tiingo API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {tiingo_api}"
    }
    params = {"startDate": start, "endDate": end, "format": "json"}
    r = requests.get(f"https://api.tiingo.com/tiingo/daily/{symbol}/prices", headers=headers, params=params, timeout=60)
    return r.json()

for s in TICKERS:
    f = RAW / f"{s}.json"
    if not f.exists():
        f.write_text(json.dumps(fetch_tiingo(s)))
        time.sleep(0.3)

pd.DataFrame([
    {
    "symbol": s, 
    "rows": len(j := json.loads((RAW/f"{s}.json").read_text())), 
    "first": j[0]["date"], 
    "last": j[-1]["date"]
    } for s in TICKERS ])

def to_frame(symbol) -> pd.DataFrame:
    df = pd.DataFrame(json.loads((RAW/f"{symbol}.json").read_text()))
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    # Map Tiingo's 'adjClose' to EODHD's 'adjusted_close' (will be updated to use just 'adj_close soon)
    if "adjClose" in df.columns and "adjusted_close" not in df.columns:
        df = df.rename(columns={"adjClose": "adjusted_close"})
    return df.set_index("date").sort_index()[["close", "adjusted_close", "volume"]].astype(float)

frames, report = {}, []
for s in TICKERS:
    d = to_frame(s)
    report.append({
        "symbol": s,
        "rows": len(d),
        "duplicate_dates": int(d.index.duplicated().sum()),
        "missing": int(d.isna().sum().sum()),
        "nonpositive_price": int((d[["close", "adjusted_close"]] <= 0).sum().sum()),
        "zero_volume_days": int((d["volume"] <= 0).sum())
    })
    frames[s] = d[~d.index.duplicated(keep="last")]

pd.DataFrame(report)
