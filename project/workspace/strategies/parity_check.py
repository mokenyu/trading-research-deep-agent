import pandas as pd
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
