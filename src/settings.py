import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(override=True)

for k in ["TINGO_API_KEY", "GOOGLE_API_KEY", "LANGSMITH_API_KEY"]:
    assert os.environ.get(k), f"missing env var: {k}"

tiingo_api = os.environ.get("TINGO_API_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent

ROOT = BASE_DIR / "project" # Path("project").resolve()
RAW = BASE_DIR / "raw_cache" # Path("raw_cache").resolve() 
WS = ROOT / "workspace" # ROOT / "workspace"
PRIVATE = ROOT / "private" # ROOT / "private"


for p in [RAW, PRIVATE, WS/"data", WS/"strategies", WS/"results", WS/"reviews"]:
    p.mkdir(parents=True, exist_ok=True)

# print("workspace: ", WS)