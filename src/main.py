import os, json, time, shutil, tempfile, subprocess, sys, traceback
import requests, importlib.util
# from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Markdown, display
from settings import eodhd_api, RAW, PRIVATE, ROOT, WS

TICKERS = ["SPY","QQQ","IWM","XLE","XLF","XLK","XLV","XLP","XLY"]
START, END = "2004-01-01", "2025-12-31"

def fetch_eod(symbol, start=START, end=END):
    params = {"api_token": eodhd_api, "from": start, "to": end, "period": "d", "fmt": "json"}
    r = requests.get(f"https://eodhd.com/api/eod/{symbol}.US", params=params, timeout=60)
    return r.json()

for s in TICKERS:
    f = RAW / f"{s}.json"
    if not f.exists():
        f.write_text(json.dumps(fetch_eod(s))); time.sleep(0.3)

pd.DataFrame([
    {
    "symbol": s, 
    "rows": len(j := json.loads((RAW/f"{s}.json").read_text())), 
    "first": j[0]["date"], 
    "last": j[-1]["date"]
    } for s in TICKERS ])
