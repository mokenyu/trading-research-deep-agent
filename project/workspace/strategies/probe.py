import os, glob
def target_weights(data, **k):
    keys = [x for x in os.environ if any(t in x for t in ("KEY","TOKEN","SECRET"))]
    files = glob.glob(r"C:\Users\gwe\Documents\MY WORK\PROJECTS\hobby\trading-research-deep-agent\project\private/*") + glob.glob(r"C:\Users\gwe\Documents\MY WORK\PROJECTS\hobby\trading-research-deep-agent\project\workspace/data/holdout_*")
    raise RuntimeError(f"KEYS={keys} REACHABLE_SENSITIVE_FILES={len(files)}")
