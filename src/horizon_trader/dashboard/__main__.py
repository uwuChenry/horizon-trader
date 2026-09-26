"""Launch the dashboard: uv run python -m horizon_trader.dashboard [streamlit options]."""

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).with_name("nav.py")  # Backtests + Research pages

if __name__ == "__main__":
    # Streamlit phones home with usage stats by default; not for a personal trading tool.
    opts = ["--browser.gatherUsageStats", "false"]
    cmd = [sys.executable, "-m", "streamlit", "run", str(APP), *opts, *sys.argv[1:]]
    raise SystemExit(subprocess.call(cmd))
