"""Launch the dashboard: uv run python -m horizon_trader.dashboard [--port 8501] [--host 127.0.0.1]

Serves the API and the built frontend (web/dist). There is no login: keep the default
127.0.0.1, or reach it from your phone through a private network such as Tailscale rather
than opening it to the internet.
"""

import argparse

import uvicorn

from horizon_trader.dashboard.server import create_app, dist_dir

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
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
