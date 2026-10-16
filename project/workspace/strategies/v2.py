import numpy as np
import pandas as pd


def target_weights(data, mom_window=126, top_n=3, vol_window=None):
    adj = data["adj_close"]
    rets = data["returns"]

    vw = mom_window if vol_window is None else vol_window

    mom = adj.pct_change(mom_window)
    vol = rets.rolling(vw).std()

    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)

    for d in dates:
        m = mom.loc[d]
        v = vol.loc[d]
        eligible = (m > 0) & (v > 0) & m.notna() & v.notna()
        if eligible.any():
            score = m[eligible] / v[eligible]
            picks = score.nlargest(top_n).index
            if len(picks):
                w.loc[d, picks] = 1.0 / len(picks)

    return w
