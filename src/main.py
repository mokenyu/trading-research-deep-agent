import os, json, time, shutil, tempfile, subprocess, sys, traceback
import requests, importlib.util
# from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Markdown, display
from settings import eodhd_api, RAW, PRIVATE, ROOT, WS

TICKERS = ["SPY","QQQ","IWM","XLE","XLF","XLK","XLV","XLP","XLY"]
START, END = "2004-01-01", "2025-12-31"

