import logging
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
EXEC_RESULTS = ROOT / "exec_results"
LOG_FILE = EXEC_RESULTS / "research_run.log"


for p in [RAW, PRIVATE, EXEC_RESULTS, WS/"data", WS/"strategies", WS/"results", WS/"reviews"]:
    p.mkdir(parents=True, exist_ok=True)


class _UnlockedFileHandler(logging.Handler):
    """Writes each log record to disk without holding a persistent OS file lock on Windows."""
    def __init__(self, path: Path):
        super().__init__(level=logging.DEBUG)
        self.path = path

    def emit(self, record):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


# Configure dual-handler logger:
# - Console (StreamHandler): INFO and above (concise progress updates only)
# - File (_UnlockedFileHandler): DEBUG and above (full tables, metrics, and detailed outputs)
logger = logging.getLogger("trading_research")
logger.setLevel(logging.DEBUG)
logger.propagate = False

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))

    file_handler = _UnlockedFileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s (%(module)s): %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


TICKERS = ["SPY","QQQ","IWM","XLE","XLF","XLK","XLV","XLP","XLY"]
START, END = "2004-01-01", "2025-12-31"
SPLITS = {
    "dev": ("2005-01-01","2017-12-31"),
    "val": ("2018-01-01","2021-12-31"),
    "holdout": ("2022-01-01","2025-12-31")
    }
WARMUP = 250