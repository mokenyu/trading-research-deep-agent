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