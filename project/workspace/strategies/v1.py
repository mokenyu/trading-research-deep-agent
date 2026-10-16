import pandas as pd


def target_weights(data, mom_window=126, vol_short=20, vol_long=120, vol_ratio_min=1.0, top_n=3):
    adj = data["adj_close"]
    mom = adj.pct_change(mom_window)

    dollar_vol = data["close"] * data["volume"]
    vol_ratio = dollar_vol.rolling(vol_short).mean() / dollar_vol.rolling(vol_long).mean()

    dates = pd.DatetimeIndex(adj.index.to_series().resample("ME").last().dropna())
    w = pd.DataFrame(0.0, index=dates, columns=adj.columns)

    for d in dates:
        m = mom.loc[d]
        vr = vol_ratio.loc[d]
        eligible = m[(m > 0) & (vr > vol_ratio_min)].dropna()
        picks = eligible.nlargest(top_n).index
        if len(picks):
            w.loc[d, picks] = 1.0 / len(picks)

    return w
