import pandas as pd
from src.settings import WS, TICKERS, logger
from src.engine import backtest, metrics, load_split

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
    d = load_split(WS / "data", split)
    rows = {}
    for name, fn in BENCHMARKS.items():
        bt = backtest(fn(d), d["returns"])
        rows[name] = metrics(bt.loc[d["eval_start"]:], d["returns"]["SPY"].loc[d["eval_start"]:])
    return pd.DataFrame(rows).T

COLS_B = ["cagr","sharpe","sortino","max_dd","ann_turnover"]

def compute_benchmarks():
    """Compute dev & val benchmark tables, write BENCHMARKS.md, and return BENCH_TEXT."""
    bench = {s: benchmark_table(s) for s in ["dev", "val"]}
    bench_text = (
        "DEVELOPMENT\n" + bench["dev"][COLS_B].to_string() +
        "\n\nVALIDATION\n" + bench["val"][COLS_B].to_string()
    )
    (WS / "BENCHMARKS.md").write_text("# Fixed benchmarks\n\n```\n" + bench_text + "\n```\n")

    ab = bench["dev"].loc["volume_mom"] - bench["dev"].loc["plain_mom"]
    logger.debug("Fixed Benchmarks:\n%s", bench_text)
    logger.info(
        "Benchmarks computed (saved to BENCHMARKS.md) | Volume filter effect on dev: "
        "sharpe %+.4f, cagr %+.4f, turnover %+.2f",
        ab["sharpe"], ab["cagr"], ab["ann_turnover"]
    )
    return bench_text