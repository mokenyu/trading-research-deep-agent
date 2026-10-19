import os, json, tempfile, subprocess, shutil, sys

from pathlib import Path
from src.settings import WS

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
    shutil.copy(Path(__file__).parent / "engine.py", sandbox / "engine.py")
    shutil.copy(Path(__file__).parent / "runner.py", sandbox / "runner.py")
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

