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