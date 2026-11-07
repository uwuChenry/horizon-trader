"""Launch the dashboard: uv run python -m horizon_trader.dashboard [--port 8501] [--host 127.0.0.1]

Serves the API and the built frontend (web/dist). The default host is HT_DASHBOARD_HOST from
.env, else 127.0.0.1. There is no login: keep 127.0.0.1, or bind a private network address
such as the machine's Tailscale IP, never the open internet.
"""

import argparse
import os

import uvicorn

import horizon_trader.config  # noqa: F401  (loads .env: HT_DASHBOARD_HOST)
from horizon_trader.dashboard.server import create_app, dist_dir

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.environ.get("HT_DASHBOARD_HOST") or "127.0.0.1")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--reload", action="store_true", help="restart on Python changes (dev)")
    args = p.parse_args()
    if not (dist_dir() / "index.html").exists():
        print("Frontend not built yet: cd web && npm install && npm run build (API still works)")
    print(f"horizon-trader dashboard on http://{args.host}:{args.port}")
    if args.reload:
        uvicorn.run(
            "horizon_trader.dashboard.server:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
    else:
        uvicorn.run(create_app(), host=args.host, port=args.port)
