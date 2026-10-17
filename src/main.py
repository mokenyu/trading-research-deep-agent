
# ==============================================================================
# CONFIG
# ==============================================================================


# adding project root
import sys
from pathlib import Path

# Determine project root relative to this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os, json, time, shutil, tempfile, subprocess, sys, traceback
import requests, importlib.util
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import logging
from src.settings import tiingo_api, RAW, PRIVATE, ROOT, WS

# Setup fallback for display and Markdown outside of IPython environments
try:
    from IPython.display import Markdown, display
except ImportError:
    def display(*args):
        for a in args:
            print(a)
    def Markdown(text):
        return text

# Suppress informational AFC warning from google-genai SDK
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

TICKERS = ["SPY","QQQ","IWM","XLE","XLF","XLK","XLV","XLP","XLY"]
START, END = "2004-01-01", "2025-12-31"


# ==============================================================================
# FETCH AND FORMAT DATA
# ==============================================================================



# ------------------------------------------------------------------------------
# Prep research data
# ------------------------------------------------------------------------------


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

print(pd.DataFrame([
    {
    "symbol": s, 
    "rows": len(j := json.loads((RAW/f"{s}.json").read_text())), 
    "first": j[0]["date"], 
    "last": j[-1]["date"]
    } for s in TICKERS ]))


# ------------------------------------------------------------------------------
# Check data for discrepancies
# ------------------------------------------------------------------------------


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

print(pd.DataFrame(report))


# ------------------------------------------------------------------------------
# Align Histories by Trading Date and Create 3 research periods.
# ------------------------------------------------------------------------------


def panel(field):
    return pd.concat({s: frames[s][field] for s in TICKERS}, axis=1)[TICKERS]

adj_close = panel("adjusted_close").dropna()
close = panel("close").loc[adj_close.index]
volume = panel("volume").loc[adj_close.index]
returns = adj_close.pct_change().fillna(0.0)

SPLITS = {
    "dev": ("2005-01-01","2017-12-31"),
    "val": ("2018-01-01","2021-12-31"),
    "holdout": ("2022-01-01","2025-12-31")
    }

WARMUP = 250

def make_split(name):
    lo, hi = SPLITS[name]; idx = adj_close.index
    first = idx[max(0, idx.searchsorted(pd.Timestamp(lo)) - WARMUP)]
    keep = (idx >= first) & (idx <= pd.Timestamp(hi))
    return {
        "adj_close": adj_close[keep],
        "close": close[keep],
        "volume": volume[keep],
        "returns": returns[keep],
        "eval_start": pd.Timestamp(lo)
    }

DATA = {name: make_split(name) for name in SPLITS}

for name in ["dev","val"]:
    for field in ["adj_close","close","volume"]:
        DATA[name][field].to_parquet(WS/"data"/f"{name}_{field}.parquet")
json.dump({k: v[0] for k,v in SPLITS.items()}, open(WS/"data"/"splits.json","w"))

DELETE_RAW_CACHE = False
if DELETE_RAW_CACHE:
    shutil.rmtree(RAW, ignore_errors=True)

print("holdout files on disk:", list(ROOT.rglob("holdout*")) or "NONE")
print(pd.DataFrame({
    n: {
        "rows": len(DATA[n]["adj_close"]), "eval_start": DATA[n]["eval_start"].date(),
        "end": DATA[n]["adj_close"].index[-1].date()
        } for n in SPLITS
    }).T)


# ------------------------------------------------------------------------------
# Clear previous run artifacts before research run
# ------------------------------------------------------------------------------


for d in [WS/"strategies", WS/"results", WS/"reviews", PRIVATE]:
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

for f in [WS/"registry.csv", WS/"decisions.jsonl", WS/"report.md", WS/"frozen.json", WS/"strategies"/"frozen.json"]:
    f.unlink(missing_ok=True)

for f in WS.glob("data/holdout_*.parquet"):
    f.unlink()

print("private:", list(PRIVATE.iterdir()) or 'empty')
print("holdout on disk:", list(ROOT.rglob('holdout*')) or "NONE")
print("workspace reset")


# ==============================================================================
# BUILD DETERMINISTIC EVALUATION LAYER
# ==============================================================================



# ------------------------------------------------------------------------------
# Create Shared Backtesting Engine
# ------------------------------------------------------------------------------


ENGINE = '''
"""Fixed backtest engine and standard metrics. Imported by the notebook AND by the isolated runner, so both compute identical numbers from identical code."""
import json
import numpy as np, pandas as pd
from pathlib import Path

PERIODS, RF_ANNUAL, MAR_ANNUAL = 252, 0.0, 0.0

def backtest(weights, returns, cost_bps=10.0):
    scheduled = pd.Series(returns.index.isin(weights.index), index=returns.index, dtype=bool)
    w = weights.reindex(returns.index).ffill().shift(1).fillna(0.0)
    is_rebal = scheduled.shift(1, fill_value=False)

    held = pd.Series(0.0, index=returns.columns)
    rows = []

    for d in returns.index:
        target = w.loc[d] if is_rebal.loc[d] else held
        traded = float((target - held).abs().sum())
        cost = traded * cost_bps / 1e4

        r = returns.loc[d]
        gross = float((target*r).sum())
        net = gross - cost

        rows.append((net, traded, cost, float(1.0 - target.sum())))

        denominator = 1.0 + gross
        if denominator <= 0:
            raise RuntimeError(f"Gross portfolio value became non-positive on {d}: gross return = {gross}")

        held = (target * (1.0 + r)) / denominator

    return pd.DataFrame(rows, index=returns.index, columns=["ret", "turnover", "cost", "cash"])

def metrics(bt, benchmark=None, rf_annual=RF_ANNUAL, mar_annual=MAR_ANNUAL):
    r = bt["ret"]
    rf_d = (1 + rf_annual) ** (1/PERIODS) - 1
    mar_d = (1 + mar_annual) ** (1/PERIODS) - 1
    ex = r - rf_d
    eq = (1 + r).cumprod(); yrs = len(r)/PERIODS
    sd = ex.std(ddof=1)
    dd = np.sqrt((np.minimum(r - mar_d, 0.0) ** 2).mean()) * np.sqrt(PERIODS)
    m = {"cagr": eq.iloc[-1] ** (1/yrs) - 1,
         "ann_ret": r.mean() * PERIODS,
         "vol": r.std(ddof=1) * np.sqrt(PERIODS),
         "sharpe": (ex.mean()/sd) * np.sqrt(PERIODS) if sd > 0 else 0.0,
         "sortino": (r.mean()*PERIODS - mar_annual)/dd if dd > 0 else 0.0,
         "max_dd": (eq/eq.cummax() - 1).min(),
         "ann_turnover": bt["turnover"].sum()/yrs,
         "ann_cost": bt["cost"].sum()/yrs,
         "avg_cash": bt["cash"].mean()}
    if benchmark is not None:
        m["bench_cagr"] = (1+benchmark).cumprod().iloc[-1] ** (1/yrs) - 1
    return {k: round(float(v), 4) for k, v in m.items()}

def load_split(data_dir, split):
    p = Path(data_dir)
    d = {f: pd.read_parquet(p/f"{split}_{f}.parquet") for f in ["adj_close","close","volume"]}
    d["returns"] = d["adj_close"].pct_change().fillna(0.0)
    d["eval_start"] = pd.Timestamp(json.load(open(p/"splits.json"))[split])
    return d
    '''

(ROOT/"engine.py").write_text(ENGINE)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine
importlib.reload(engine)
from engine import backtest, metrics
print("engine.py has been written!")


# ------------------------------------------------------------------------------
# Verify Portfolio Accounting
# ------------------------------------------------------------------------------


w = pd.DataFrame(0.0, index=[DATA["dev"]["adj_close"].index[0]], columns=TICKERS)
w.iloc[0, 0] = 1.0
assert round(backtest(w, DATA["dev"]["returns"]).turnover.sum(), 4) == 1.0
print("turnover check ok")


# ------------------------------------------------------------------------------
# Establish Fixed Benchmarks
# ------------------------------------------------------------------------------


def bh_weights(data, tickers):
    w = pd.DataFrame(0.0, index=[data["adj_close"].index[0]], columns=data["adj_close"].columns)
    w.loc[w.index[0], tickers] = 1.0/len(tickers)
    return w

def plain_momentum(data, mom_window=126, top_n=3):
    adj = data["adj_close"]; mom = adj.pct_change(mom_window)
    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)
    for dt in dates:
        picks = mom.loc[dt][mom.loc[dt] > 0].dropna().nlargest(top_n).index
        if len(picks): w.loc[dt, picks] = 1.0/len(picks)
    return w

def volume_momentum(data, mom_window=126, top_n=3, vol_short=20, vol_long=120, vol_ratio_min=1.0):
    adj, cls, vol = data["adj_close"], data["close"], data["volume"]
    mom = adj.pct_change(mom_window); dv = cls*vol
    ratio = dv.rolling(vol_short).mean()/dv.rolling(vol_long).mean()
    ok = (mom > 0) & (ratio > vol_ratio_min)
    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)
    for dt in dates:
        picks = mom.loc[dt][ok.loc[dt]].dropna().nlargest(top_n).index
        if len(picks): w.loc[dt, picks] = 1.0/len(picks)
    return w

BENCHMARKS = {"spy_bh": lambda d: bh_weights(d, ["SPY"]),
              "ew_bh": lambda d: bh_weights(d, TICKERS),
              "plain_mom": plain_momentum, "volume_mom": volume_momentum}

def benchmark_table(split):
    d = DATA[split]; rows = {}
    for name, fn in BENCHMARKS.items():
        bt = backtest(fn(d), d["returns"])
        rows[name] = metrics(bt.loc[d["eval_start"]:], d["returns"]["SPY"].loc[d["eval_start"]:])
    return pd.DataFrame(rows).T

COLS_B = ["cagr","sharpe","sortino","max_dd","ann_turnover"]
BENCH = {s: benchmark_table(s) for s in ["dev","val"]}
BENCH_TEXT = ("DEVELOPMENT\n" + BENCH["dev"][COLS_B].to_string() +
              "\n\nVALIDATION\n" + BENCH["val"][COLS_B].to_string())
(WS/"BENCHMARKS.md").write_text("# Fixed benchmarks\n\n```\n" + BENCH_TEXT + "\n```\n")

ab = BENCH["dev"].loc["volume_mom"] - BENCH["dev"].loc["plain_mom"]
print(BENCH["dev"][COLS_B])
print(f"\nvolume filter effect on dev: sharpe {ab['sharpe']:+.4f}, "
      f"cagr {ab['cagr']:+.4f}, turnover {ab['ann_turnover']:+.2f}")


# ------------------------------------------------------------------------------
# Create Isolated Processes for Execution
# ------------------------------------------------------------------------------


RUNNER = '''
"""Isolated strategy runner. Own process, temp sandbox, scrubbed environment."""
import sys, json, importlib.util, traceback

def main():
    strat, params_json, data_dir, split, cost_bps = sys.argv[1:6]
    import engine
    d = engine.load_split(data_dir, split)
    spec = importlib.util.spec_from_file_location("strategy", strat)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    w = mod.target_weights(d, **json.loads(params_json))
    bt = engine.backtest(w, d["returns"], cost_bps=float(cost_bps))
    ev = bt.loc[d["eval_start"]:]
    bench = d["returns"]["SPY"].loc[d["eval_start"]:] if "SPY" in d["returns"] else None
    print(json.dumps({"ok": True, "metrics": engine.metrics(ev, bench),
                      "equity": [round(float(x), 6) for x in (1+ev["ret"]).cumprod().tolist()],
                      "dates": [str(x.date()) for x in ev.index]}))

if __name__ == "__main__":
    try: main()
    except Exception: print(json.dumps({"ok": False, "error": traceback.format_exc(limit=3)}))
'''
(ROOT/"runner.py").write_text(RUNNER)

def isolated_environment(sandbox):

    required = ["PATH","SYSTEMROOT","WINDIR","COMSPEC","PATHEXT","VIRTUAL_ENV","CONDA_PREFIX","CONDA_DEFAULT_ENV","LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH","LANG","LC_ALL"]

    env = {name: os.environ[name] for name in required if name in os.environ}

    env.update({
        "HOME": str(sandbox),
        "USERPROFILE": str(sandbox),
        "TEMP": str(sandbox),
        "TMP": str(sandbox),
        "TMPDIR": str(sandbox),
        "PYTHONHASHSEED": "1",
        "PYTHONUTF8": "1",
    })

    return env

def run_isolated(strategy_path, params, split, cost_bps=10.0, timeout=600):
    sandbox = Path(tempfile.mkdtemp(prefix="strat_"))
    (sandbox/"data").mkdir()
    for f in ["adj_close","close","volume"]:
        shutil.copy(WS/"data"/f"{split}_{f}.parquet", sandbox/"data")
    shutil.copy(WS/"data"/"splits.json", sandbox/"data")
    shutil.copy(ROOT/"engine.py", sandbox); shutil.copy(ROOT/"runner.py", sandbox)
    shutil.copy(strategy_path, sandbox/"strategy.py")
    try:
        p = subprocess.run([sys.executable, "runner.py", "strategy.py", json.dumps(params),
                            "data", split, str(cost_bps)],
                           capture_output=True, text=True, cwd=sandbox, timeout=timeout,
                           env=isolated_environment(sandbox))
        if not p.stdout.strip():
            return {"ok": False, "error": (p.stderr or "no output")[-400:]}
        return json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ------------------------------------------------------------------------------
# Verify Execution Parity and Data Boundaries
# ------------------------------------------------------------------------------


(WS/"strategies"/"parity_check.py").write_text('''import pandas as pd
def target_weights(data, mom_window=126, top_n=3, vol_short=20, vol_long=120, vol_ratio_min=1.0):
    adj, cls, vol = data["adj_close"], data["close"], data["volume"]
    mom = adj.pct_change(mom_window); dv = cls*vol
    ratio = dv.rolling(vol_short).mean()/dv.rolling(vol_long).mean()
    ok = (mom>0)&(ratio>vol_ratio_min)
    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)
    for d in dates:
        picks = mom.loc[d][ok.loc[d]].dropna().nlargest(top_n).index
        if len(picks): w.loc[d,picks]=1.0/len(picks)
    return w
''')
iso = run_isolated(WS/"strategies"/"parity_check.py", {"mom_window":126,"top_n":3}, "dev")
d = DATA["dev"]
inp = metrics(backtest(volume_momentum(d, 126, 3), d["returns"]).loc[d["eval_start"]:],
              d["returns"]["SPY"].loc[d["eval_start"]:])
assert iso["metrics"]["sharpe"] == inp["sharpe"], "isolated and in-process disagree"
print("parity ok:", iso["metrics"]["sharpe"])

PROBE = f'''import os, glob
def target_weights(data, **k):
    keys = [x for x in os.environ if any(t in x for t in ("KEY","TOKEN","SECRET"))]
    files = glob.glob(r"{PRIVATE}/*") + glob.glob(r"{WS}/data/holdout_*")
    raise RuntimeError(f"KEYS={{keys}} REACHABLE_SENSITIVE_FILES={{len(files)}}")
'''
(WS/"strategies"/"probe.py").write_text(PROBE)
msg = run_isolated(WS/"strategies"/"probe.py", {}, "dev")["error"].strip().split("\n")[-1]
print("probe:", msg)
assert "KEYS=[]" in msg, "credentials reachable from the sandbox"
assert "REACHABLE_SENSITIVE_FILES=0" in msg, "holdout or private files reachable from the sandbox"


# ==============================================================================
# CREATE EXPERIMENT AND DECISION LAYER
# ==============================================================================



# ------------------------------------------------------------------------------
# Create Experiment Registry
# ------------------------------------------------------------------------------


REGISTRY = WS / "registry.csv"
DECISIONS = WS / "decisions.jsonl"
MAX_CONFIGS = 12
COLS = ["version","run","status","params","note","dev_cagr","dev_sharpe","dev_sortino",
        "dev_max_dd","dev_turnover","val_cagr","val_sharpe","val_max_dd","dev_cagr_20bps","error"]

def _used(version):
    if not REGISTRY.exists(): return 0
    return int((pd.read_csv(REGISTRY)["version"] == version).sum())

def _decisions():
    if not DECISIONS.exists(): return []
    return [json.loads(l) for l in DECISIONS.read_text().splitlines() if l.strip()]

def _stage_ok(version):
    """vN cannot begin until v(N-1) is swept, reviewed and decided."""
    if not (version.startswith("v") and version[1:].isdigit()): return True, ""
    n = int(version[1:])
    if n <= 1: return True, ""
    prev = f"v{n-1}"
    if not REGISTRY.exists() or _used(prev) == 0:
        return False, f"stage gate: {prev} has no recorded runs. Complete {prev} first."
    reg = pd.read_csv(REGISTRY)
    if reg[(reg.version == prev) & (reg.status == "ok")].empty:
        return False, f"stage gate: {prev} has no successful runs."
    if not (WS/"reviews"/f"{prev}.md").exists():
        return False, f"stage gate: /reviews/{prev}.md does not exist. Get a critic review first."
    if not any(d["version"] == prev for d in _decisions()):
        return False, f"stage gate: no decision recorded for {prev}. Call record_decision first."
    return True, ""


# ------------------------------------------------------------------------------
# Create Research Tools
# ------------------------------------------------------------------------------


from langchain.tools import tool

@tool
def sweep(version: str, grid_json: str, note: str = "") -> str:
    """Backtest strategies/<version>.py over several parameter sets in ONE call.

    version   : file stem, e.g. "v1" for strategies/v1.py
    grid_json : JSON list of parameter objects, e.g. [{"top_n":3},{"top_n":4}]
    note      : short reason for this sweep

    Runs each configuration in an isolated subprocess. Returns a CSV table sorted by
    validation Sharpe. Max 12 configurations per version, cumulative. Every row is
    written to registry.csv, including failures. vN is blocked until v(N-1) is swept,
    reviewed and decided.
    """
    ok, why = _stage_ok(version)
    if not ok: return f"error: {why}"
    used = _used(version)
    try:
        grid = json.loads(grid_json)
        if isinstance(grid, dict): grid = [grid]
    except Exception as e:
        return f"error: grid_json is not valid JSON ({e})"
    if used + len(grid) > MAX_CONFIGS:
        return f"error: budget. {used}/{MAX_CONFIGS} used on {version}, you asked for {len(grid)} more."
    path = WS/"strategies"/f"{version}.py"
    if not path.exists():
        return f"error: {path.name} does not exist. Write it first."

    rows = []
    for i, params in enumerate(grid, start=used + 1):
        row = {"version": version, "run": i, "note": note,
               "params": json.dumps(params, separators=(",", ":"))}
        dev = run_isolated(path, params, "dev")
        if not dev["ok"]:
            row.update(status="error", error=dev["error"].strip().split("\n")[-1][:150])
            rows.append(row); continue
        val = run_isolated(path, params, "val")
        c20 = run_isolated(path, params, "dev", cost_bps=20.0)
        dm, vm = dev["metrics"], val["metrics"]
        row.update(status="ok", dev_cagr=dm["cagr"], dev_sharpe=dm["sharpe"],
                   dev_sortino=dm["sortino"], dev_max_dd=dm["max_dd"],
                   dev_turnover=dm["ann_turnover"], val_cagr=vm["cagr"],
                   val_sharpe=vm["sharpe"], val_max_dd=vm["max_dd"],
                   dev_cagr_20bps=c20["metrics"]["cagr"] if c20["ok"] else None)
        tag = f"{version}_run{i}"
        (WS/"results"/f"{tag}.json").write_text(json.dumps({"params": params, "dev": dm, "val": vm}, indent=2))
        eq = pd.Series(dev["equity"], index=pd.to_datetime(dev["dates"]))
        plt.figure(figsize=(8,3)); plt.plot(eq); plt.yscale("log"); plt.title(tag)
        plt.tight_layout(); plt.savefig(WS/"results"/f"{tag}.png", dpi=90); plt.close("all")
        rows.append(row)

    df = pd.DataFrame(rows).reindex(columns=COLS)
    df.to_csv(REGISTRY, mode="a", header=not REGISTRY.exists(), index=False)
    out = df.drop(columns=["version","note"]).round(3).dropna(axis=1, how="all")
    if "val_sharpe" in out:
        out = out.sort_values("val_sharpe", ascending=False, na_position="last")
    return out.to_csv(index=False)

@tool
def read_registry(version: str = "") -> str:
    """Every run recorded so far as CSV, accepted and rejected. Pass a version to filter."""
    if not REGISTRY.exists(): return "empty"
    r = pd.read_csv(REGISTRY)
    if version: r = r[r["version"] == version]
    return r[["version","run","status","params","dev_sharpe","dev_sortino",
              "dev_max_dd","val_sharpe","val_max_dd","error"]].to_csv(index=False)

@tool
def record_decision(version: str, champion: str, rationale: str, params_json: str) -> str:
    """Record the approved outcome of a version. REQUIRED before the next version can be swept.

    version    : the version just reviewed, e.g. "v2"
    champion   : which version is champion after applying the selection rule
    rationale  : cite the selection rule and the specific numbers that decided it
    params_json: the champion's parameters as JSON
    """
    if any(d["version"] == version for d in _decisions()):
        return f"error: a decision for {version} already exists and cannot be overwritten."
    rec = {"version": version, "champion": champion, "rationale": rationale,
           "params": json.loads(params_json), "ts": time.time()}
    with DECISIONS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return f"recorded. champion is now {champion}"


# ------------------------------------------------------------------------------
# Fix Strategy Selection Rule
# ------------------------------------------------------------------------------


SELECTION_RULE = """
# Version selection rule (fixed before any version was run)

A challenger replaces the incumbent champion only if it passes ALL THREE gates:

1. Validation Sharpe is not worse than the incumbent's
2. Validation max drawdown is within 2 percentage points of the incumbent's
3. Development annual turnover is no more than 20% above the incumbent's

Ties go to the incumbent. A newer version does not automatically replace an older one.
A higher development Sharpe is not sufficient and is not one of the gates.
"""
(WS/"SELECTION_RULE.md").write_text(SELECTION_RULE)

def select_champion(challenger, incumbent, name_c, name_i):
    if incumbent is None: return name_c, "no incumbent"
    checks = [("validation Sharpe not worse",
               challenger["val_sharpe"] >= incumbent["val_sharpe"]),
              ("validation drawdown within 2pp",
               challenger["val_max_dd"] >= incumbent["val_max_dd"] - 0.02),
              ("turnover within +20%",
               challenger["dev_turnover"] <= incumbent["dev_turnover"] * 1.20)]
    failed = [n for n, ok in checks if not ok]
    if failed:
        return name_i, "incumbent retained; challenger failed: " + "; ".join(failed)
    return name_c, "challenger passed all three gates"

def best_of(version):
    reg = pd.read_csv(REGISTRY)
    rows = reg[(reg.version == version) & (reg.status == "ok")]
    return None if rows.empty else rows.sort_values("val_sharpe", ascending=False).iloc[0]

print(SELECTION_RULE)


# ==============================================================================
# ESTABLISH MANUAL BASELINE
# ==============================================================================


def manual_baseline(data, mom_window=126, vol_short=20, vol_long=120,
                    vol_ratio_min=1.0, top_n=3):
    adj, cls, vol = data["adj_close"], data["close"], data["volume"]
    mom = adj.pct_change(mom_window)
    dv = cls * vol
    ratio = dv.rolling(vol_short).mean() / dv.rolling(vol_long).mean()
    ok = (mom > 0) & (ratio > vol_ratio_min)
    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)
    for d in dates:
        picks = mom.loc[d][ok.loc[d]].dropna().nlargest(top_n).index
        if len(picks):
            w.loc[d, picks] = 1.0 / len(picks)
    return w

d = DATA["dev"]
bt = backtest(manual_baseline(d), d["returns"])
ev = bt.loc[d["eval_start"]:]
spy = d["returns"]["SPY"].loc[d["eval_start"]:]
print(metrics(ev, spy))

fig, ax = plt.subplots(2, 1, figsize=(9, 5), sharex=True, height_ratios=[2, 1])
eq = (1 + ev["ret"]).cumprod()
ax[0].plot(eq, label="strategy"); ax[0].plot((1 + spy).cumprod(), label="SPY")
ax[0].set_yscale("log"); ax[0].legend(); ax[0].set_title("Development 2005-2017")
ax[1].fill_between(eq.index, (eq / eq.cummax() - 1), 0, alpha=.4)
ax[1].set_ylabel("drawdown")
plt.tight_layout()
plt.show()


# ==============================================================================
# DEEP AGENTS RESEARCH TEAM CONFIGURATION
# ==============================================================================



# ------------------------------------------------------------------------------
# Set Agent Roles and Boundaries
# ------------------------------------------------------------------------------

from deepagents import create_deep_agent, FilesystemPermission
from deepagents.backends import FilesystemBackend
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from src.agents import COORDINATOR, critic, engineer

MODEL_ID = "google_genai:gemini-4-argon"
WORKER = init_chat_model(MODEL_ID, reasoning_effort="low") # reasoning={"effort": "low"} for openai models
MANAGER = init_chat_model(MODEL_ID, reasoning_effort="medium")

agent = create_deep_agent(
    model=MANAGER,
    tools=[sweep, read_registry, record_decision],
    system_prompt=COORDINATOR,
    subagents=[engineer, critic],
    backend=FilesystemBackend(root_dir=str(WS), virtual_mode=True),
    checkpointer=InMemorySaver(),
    name="coordinator",
)

# Helper function for invoking coordinator

THREAD = {"configurable": {"thread_id": "1"}}

def run(prompt: str, version: str = "v1"):
    out = agent.invoke({"messages": [{"role":"user","content":prompt}]}, THREAD)
    c = out["messages"][-1].content
    print(c if isinstance(c, str) else
          "\n".join(b.get("text","") for b in c if b.get("type") == "text"))
    return out

print("subagent models:", engineer["model"].model, critic["model"].model)
print(WORKER.invoke("reply with the single word: ok").content)


# ==============================================================================
# REPRODUCE MANUAL BASELINE AS V1
# ==============================================================================

def main():
    V1_BRIEF = """Build Version 1, the baseline.

    Delegate to strategy-engineer. /strategies/v1.py: 126-day momentum from adjusted close;
    20-day over 120-day average dollar volume from raw close x raw volume; eligible if
    momentum > 0 and volume ratio > 1.0; rank eligible by momentum, hold top 3 equal weight,
    rebalance monthly, cash otherwise. Parameters: mom_window, vol_short, vol_long,
    vol_ratio_min, top_n.

    Sweep exactly these nine in one call: mom_window in (63, 126, 189) crossed with
    top_n in (2, 3, 4), everything else at default.

    Pass the table to research-critic for a review of v1, telling it to compare against the
    fixed benchmarks. Then apply the selection rule (v1 has no incumbent, so it becomes the
    champion by default) and call record_decision for v1.

    Finally report: the chosen configuration, how it compares to equal-weight buy-and-hold
    and plain momentum, and the critic's proposal with your decision."""

    _ = run(V1_BRIEF)


    # ==============================================================================
    # AGENT STRATEGY REVISION: TEST MARKET-REGIME FILTER IN V2
    # ==============================================================================


    V2_BRIEF = """Review the critic's v1 proposal in /reviews/v1.md. If you approve it, have
    strategy-engineer implement it as /strategies/v2.py. Do not modify v1.py.
    Sweep at most 12 configurations in one call. Pass the table to research-critic for a
    review written to /reviews/v2.md. Then apply the selection rule between v2 and the
    current champion, state which of the three gates passed and which failed, and call
    record_decision for v2. Do not proceed past that."""

    _ = run(V2_BRIEF)

    # Verify if v2 experiments, review and decision have been persisted

    print(pd.read_csv(REGISTRY).groupby(["version","status"]).size())
    print("decisions:", [d["version"] for d in _decisions()])
    assert (WS/"reviews"/"v2.md").exists(), "v2 review missing"
    assert any(d["version"] == "v2" for d in _decisions()), "v2 decision missing"
    print("v2 cycle complete")


    # ==============================================================================
    # RUN FINAL REVISION IN V3
    # ==============================================================================


    V3_BRIEF = """Implement the final approved revision as /strategies/v3.py. Do not modify
    v1 or v2. Sweep at most 12 configurations in one call, get a critic review at
    /reviews/v3.md, apply the selection rule, and call record_decision for v3.

    Then write /strategies/frozen.json containing exactly:
    {"version": "<champion version>", "params": {...}, "rationale": "..."}
    where the version is whichever the selection rule says is champion, which may be v1 or
    v2 rather than v3. After writing that file, stop."""

    _ = run(V3_BRIEF)

    display(Markdown("### Decision log"))
    for dd_ in _decisions():
        print(f"{dd_['version']} -> champion {dd_['champion']}: {dd_['rationale'][:160]}")
    print("\nfrozen:", (WS/"strategies"/"frozen.json").read_text())


    # ==============================================================================
    # FREEZE THE CHAMPION AND UNLOCK HOLDOUT
    # ==============================================================================


    frozen = json.loads((WS/"strategies"/"frozen.json").read_text())
    print("frozen:", frozen)
    assert len(_decisions()) == 3, f"expected 3 decisions, found {len(_decisions())}"
    for v in ["v1","v2","v3"]:
        assert (WS/"reviews"/f"{v}.md").exists(), f"missing review for {v}"
        assert not pd.read_csv(REGISTRY).query(f"version=='{v}' and status=='ok'").empty, f"no runs for {v}"
    print("all three cycles complete")

    for field in ["adj_close","close","volume"]:
        DATA["holdout"][field].to_parquet(WS/"data"/f"holdout_{field}.parquet")

    final = {}
    for split in ["dev","val","holdout"]:
        res = run_isolated(WS/"strategies"/f"{frozen['version']}.py", frozen["params"], split)
        assert res["ok"], res["error"]
        final[split] = res["metrics"]
        plt.plot(pd.Series(res["equity"], index=pd.to_datetime(res["dates"])), label=split)
    plt.yscale("log"); plt.legend(); plt.title(f"frozen {frozen['version']} across all periods"); plt.show()

    (WS/"results"/"holdout.json").write_text(json.dumps(final, indent=2))
    BENCH_HOLD = benchmark_table("holdout")
    comparison = pd.concat([pd.DataFrame(final).T.assign(source="strategy"),
                            BENCH_HOLD.assign(source="benchmark_holdout")])
    print(comparison[["cagr","sharpe","sortino","max_dd","ann_turnover","source"]])


    # ==============================================================================
    # AUDIT COMPLETE RESEARCH TRAIL
    # ==============================================================================


    REPORT_BRIEF = f"""The holdout has been run once and the strategy is frozen. Nothing can change now.

    Frozen: {json.dumps(frozen)}
    Metrics by period: {json.dumps(final)}
    Holdout benchmarks: {BENCH_HOLD[COLS_B].to_json()}

    Call read_registry once with no argument, read /decisions.jsonl and every file in
    /reviews/, then write /report.md covering:

    1. What changed at each version and what evidence drove it
    2. How the selection rule decided each champion, including gates that failed
    3. Whether the revisions improved the research case, separately from returns
    4. How the frozen strategy compares to SPY buy-and-hold, equal-weight buy-and-hold,
    and plain momentum on the holdout
    5. Whether the volume filter earned its turnover
    6. Where you made weak decisions, accepted thin evidence, or got lucky

    Cite run numbers from the registry. Do not defend the result."""

    _ = run(REPORT_BRIEF)

    # Render report alongside full experiment registry and verify version data

    display(Markdown("## Agent report"))
    display(Markdown((WS / "report.md").read_text(encoding="utf-8")))

    display(Markdown("## Experiment registry"))
    reg = pd.read_csv(REGISTRY)
    display(reg[["version","run","status","params","dev_sharpe","dev_sortino",
                "dev_max_dd","dev_turnover","val_sharpe","val_max_dd","dev_cagr_20bps"]])
    print("versions with runs:", sorted(reg["version"].unique()))
    print("decisions recorded:", [d["version"] for d in _decisions()])
    print("reviews on disk:  ", sorted(p.stem for p in (WS/"reviews").glob("*.md")))

if __name__ == "__main__":
    main()
