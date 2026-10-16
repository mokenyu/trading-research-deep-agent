import numpy as np
import pandas as pd


def target_weights(data, mom_window=126, top_n=3, vol_window=None, rank_buffer=1):
    adj = data["adj_close"]
    rets = data["returns"]

    vw = mom_window if vol_window is None else vol_window

    mom = adj.pct_change(mom_window)
    vol = rets.rolling(vw).std()

    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)

    held = set()

    for d in dates:
        m = mom.loc[d]
        v = vol.loc[d]
        eligible = (m > 0) & (v > 0) & m.notna() & v.notna()
        if eligible.any():
            score = (m[eligible] / v[eligible]).sort_values(ascending=False)
            ranked_assets = list(score.index)
            max_keep_rank = top_n + rank_buffer

            retained = [
                asset
                for rank_idx, asset in enumerate(ranked_assets, start=1)
                if asset in held and rank_idx <= max_keep_rank
            ][:top_n]

            slots_left = top_n - len(retained)
            if slots_left > 0:
                retained_set = set(retained)
                additions = [
                    asset for asset in ranked_assets if asset not in retained_set
                ][:slots_left]
                picks = retained + additions
            else:
                picks = retained

            if len(picks):
                w.loc[d, picks] = 1.0 / top_n
                held = set(picks)
            else:
                held = set()
        else:
            held = set()

    return w
