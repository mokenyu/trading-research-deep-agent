import json, time
import pandas as pd
import matplotlib.pyplot as plt
from langchain.tools import tool
from src.isolated_exec import run_isolated
from src.settings import WS

# Create Reseach Registry

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


# Create Research Tools

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