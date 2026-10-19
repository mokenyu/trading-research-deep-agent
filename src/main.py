
# adding project root
import sys
from pathlib import Path

# Determine project root relative to this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os, json, time, shutil
import requests
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import logging

from src.settings import tiingo_api, RAW, PRIVATE, ROOT, WS
from src.settings import TICKERS, START, END, SPLITS, WARMUP
from src.engine import backtest, metrics

from src.isolated_exec import run_isolated
from src.governance import _decisions, REGISTRY
from src.benchmarks import benchmark_table, COLS_B, volume_momentum

# Suppress informational AFC warning from google-genai SDK
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from IPython.display import Markdown, display


## FETCH AND FORMAT DATA

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


## Check data for discrepancies


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


## Align Histories by Trading Date and Create 3 research periods.


def panel(field):
    return pd.concat({s: frames[s][field] for s in TICKERS}, axis=1)[TICKERS]

adj_close = panel("adjusted_close").dropna()
close = panel("close").loc[adj_close.index]
volume = panel("volume").loc[adj_close.index]
returns = adj_close.pct_change().fillna(0.0)

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


## Clear previous run artifacts before research run


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


## Verify Portfolio Accounting


w = pd.DataFrame(0.0, index=[DATA["dev"]["adj_close"].index[0]], columns=TICKERS)
w.iloc[0, 0] = 1.0
assert round(backtest(w, DATA["dev"]["returns"]).turnover.sum(), 4) == 1.0
print("turnover check ok")


## Verify Execution Parity and Data Boundaries


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


# ESTABLISH MANUAL BASELINE

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

# DEEP AGENTS RESEARCH TEAM CONFIGURATION

def run(prompt: str, agent, thread):
    out = agent.invoke({"messages": [{"role":"user","content":prompt}]}, {"configurable": {"thread_id": thread}})
    c = out["messages"][-1].content
    print(c if isinstance(c, str) else
          "\n".join(b.get("text","") for b in c if b.get("type") == "text"))
    return out


def main():
    from src.agents import agent

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

    _ = run(V1_BRIEF, agent, "v1")


    # AGENT STRATEGY REVISION: TEST MARKET-REGIME FILTER IN V2

    V2_BRIEF = """Review the critic's v1 proposal in /reviews/v1.md. If you approve it, have
    strategy-engineer implement it as /strategies/v2.py. Do not modify v1.py.
    Sweep at most 12 configurations in one call. Pass the table to research-critic for a
    review written to /reviews/v2.md. Then apply the selection rule between v2 and the
    current champion, state which of the three gates passed and which failed, and call
    record_decision for v2. Do not proceed past that."""

    _ = run(V2_BRIEF, agent, "v2")

    # Verify if v2 experiments, review and decision have been persisted

    print(pd.read_csv(REGISTRY).groupby(["version","status"]).size())
    print("decisions:", [d["version"] for d in _decisions()])
    assert (WS/"reviews"/"v2.md").exists(), "v2 review missing"
    assert any(d["version"] == "v2" for d in _decisions()), "v2 decision missing"
    print("v2 cycle complete")


    # RUN FINAL REVISION IN V3

    V3_BRIEF = """Implement the final approved revision as /strategies/v3.py. Do not modify
    v1 or v2. Sweep at most 12 configurations in one call, get a critic review at
    /reviews/v3.md, apply the selection rule, and call record_decision for v3.

    Then write /strategies/frozen.json containing exactly:
    {"version": "<champion version>", "params": {...}, "rationale": "..."}
    where the version is whichever the selection rule says is champion, which may be v1 or
    v2 rather than v3. After writing that file, stop."""

    _ = run(V3_BRIEF, agent, "v3")

    display(Markdown("### Decision log"))
    for dd_ in _decisions():
        print(f"{dd_['version']} -> champion {dd_['champion']}: {dd_['rationale'][:160]}")
    print("\nfrozen:", (WS/"strategies"/"frozen.json").read_text())


    # FREEZE THE CHAMPION AND UNLOCK HOLDOUT

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


    # AUDIT COMPLETE RESEARCH TRAIL

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

    _ = run(REPORT_BRIEF, agent, "brief")

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
