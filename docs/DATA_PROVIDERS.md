# Market Data Providers & Alternatives Guide

## 1. Context & Motivation

The original handbook implementation relied on **EODHD** for historical end-of-day data. However, **EODHD is an unfavorable choice on its free tier**:
- The free plan restricts historical data to **1 year (or ~60 days)**.
- Running multi-year quantitative backtests (2004–2025) requires a paid subscription ($20–$30/month).
- Without a paid tier, data splits (`dev`, `val`, `holdout`) will be empty and raise `IndexError`.

This document explains the setup for **Tiingo** (generous free tier with registration) and **yfinance** (100% free, no API key), as well as reference code for **EODHD** if a paid key is used.

---

## 2. Provider Comparison

| Provider | Status in Project | Cost | API Key | Setup Complexity | Historical Depth |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tiingo** | **Current Choice** | **Free tier** | Required (Free signup) | Low (Token in `.env`) | 30+ years |
| **yfinance** | **Zero-Auth Alt** | **Free** | None | Instant (Install package) | 20+ years |
| **EODHD** | **Previous Choice (Unfavorable)** | ~$20–$30/mo | Required | Paid tier needed | 20+ years |

---

## 3. Option A: Tiingo (Current Project Setup)

Tiingo offers a free tier with 30+ years of daily US ETF history.

### Step 1: Add Token to `.env`
Sign up at [tiingo.com](https://www.tiingo.com) and add your token:
```env
TIINGO_API_KEY=your_tiingo_token_here
```

### Step 2: Update `src/settings.py`
Add environment variable validation and export `tiingo_api`:

```python
# In src/settings.py
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(override=True)

for k in ["TIINGO_API_KEY", "GOOGLE_API_KEY", "LANGSMITH_API_KEY"]:
    assert os.environ.get(k), f"missing env var: {k}"

tiingo_api = os.environ.get("TIINGO_API_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT = BASE_DIR / "project"
RAW = BASE_DIR / "raw_cache"
WS = ROOT / "workspace"
PRIVATE = ROOT / "private"

for p in [RAW, PRIVATE, WS / "data", WS / "strategies", WS / "results", WS / "reviews"]:
    p.mkdir(parents=True, exist_ok=True)
```

### Step 3: Implement in `src/main.py` / `src/notebooks/main.ipynb`
Import `tiingo_api` and use `fetch_tiingo()`. 

> [!IMPORTANT]
> Tiingo returns column name `adjClose` (camelCase) and ISO timestamps with UTC timezone (`Z`). `to_frame()` normalizes column names and strips timezone to remain compatible with tz-naive split timestamps.

```python
# In src/main.py or src/notebooks/main.ipynb
import json, time, requests
import pandas as pd
from src.settings import tiingo_api, RAW, TICKERS, START, END

def fetch_tiingo(symbol: str, start: str = START, end: str = END):
    """Fetch daily data from Tiingo API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {tiingo_api}"
    }
    params = {"startDate": start, "endDate": end, "format": "json"}
    r = requests.get(f"https://api.tiingo.com/tiingo/daily/{symbol}/prices", headers=headers, params=params, timeout=60)
    return r.json()

# Download and cache raw JSON files
for s in TICKERS:
    f = RAW / f"{s}.json"
    if not f.exists():
        f.write_text(json.dumps(fetch_tiingo(s)))
        time.sleep(0.3)

def to_frame(symbol: str) -> pd.DataFrame:
    df = pd.DataFrame(json.loads((RAW / f"{symbol}.json").read_text()))
    # Normalize Tiingo's UTC timezone to tz-naive
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    # Rename Tiingo's 'adjClose' to 'adjusted_close'
    if "adjClose" in df.columns and "adjusted_close" not in df.columns:
        df = df.rename(columns={"adjClose": "adjusted_close"})
    return df.set_index("date").sort_index()[["close", "adjusted_close", "volume"]].astype(float)
```

---

## 4. Option B: `yfinance` (Free, No API Key Required)

If you don't want to register for any API tokens, `yfinance` fetches public daily bars directly.

### Step 1: Install Package
```powershell
uv add yfinance
```

### Step 2: Implementation in `src/main.py` / `src/notebooks/main.ipynb`
```python
# In src/main.py or src/notebooks/main.ipynb
import json
import pandas as pd
import yfinance as yf
from src.settings import RAW, TICKERS, START, END

def fetch_yfinance(symbol: str, start: str = START, end: str = END):
    """Fetch full daily history via yfinance."""
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    records = []
    for dt, row in df.iterrows():
        records.append({
            "date": dt.strftime("%Y-%m-%d"),
            "close": float(row["Close"]),
            "adjusted_close": float(row["Adj Close"]),
            "volume": float(row["Volume"])
        })
    return records

# Download and cache raw JSON files
for s in TICKERS:
    f = RAW / f"{s}.json"
    if not f.exists():
        f.write_text(json.dumps(fetch_yfinance(s)))

def to_frame(symbol: str) -> pd.DataFrame:
    df = pd.DataFrame(json.loads((RAW / f"{symbol}.json").read_text()))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()[["close", "adjusted_close", "volume"]].astype(float)
```

---

## 5. Option C: EODHD (Previous Handbook Method — Requires Paid Plan)

If you have a paid EODHD API subscription, here is the original handbook code.

### Step 1: Add Token to `.env`
```env
EODHD_API_KEY=your_paid_eodhd_key
```

### Step 2: In `src/settings.py`
```python
# In src/settings.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)
assert os.environ.get("EODHD_API_KEY"), "missing env var: EODHD_API_KEY"
eodhd_api = os.environ.get("EODHD_API_KEY")
```

### Step 3: In `src/main.py` / `src/notebooks/main.ipynb`
```python
# In src/main.py or src/notebooks/main.ipynb
import json, time, requests
import pandas as pd
from src.settings import eodhd_api, RAW, TICKERS, START, END

def fetch_eodhd(symbol: str, start: str = START, end: str = END):
    params = {"api_token": eodhd_api, "from": start, "to": end, "period": "d", "fmt": "json"}
    r = requests.get(f"https://eodhd.com/api/eod/{symbol}.US", params=params, timeout=60)
    return r.json()

for s in TICKERS:
    f = RAW / f"{s}.json"
    if not f.exists():
        f.write_text(json.dumps(fetch_eodhd(s)))
        time.sleep(0.3)

def to_frame(symbol: str) -> pd.DataFrame:
    df = pd.DataFrame(json.loads((RAW / f"{symbol}.json").read_text()))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()[["close", "adjusted_close", "volume"]].astype(float)
```
