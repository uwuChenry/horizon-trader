"""The dashboard server: a read-only JSON API plus the built React app (web/dist).

uv run python -m horizon_trader.dashboard            # http://127.0.0.1:8501
cd web && npm run dev                                # frontend dev server, proxies /api
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from horizon_trader import config
from horizon_trader.dashboard.routes import backtests, journal, live, orb, studies


def dist_dir() -> Path:
    return config.REPO_ROOT / "web" / "dist"


def create_app(static: Path | None = None) -> FastAPI:
    app = FastAPI(title="horizon-trader", docs_url="/api/docs", openapi_url="/api/openapi.json")
    for module in (studies, backtests, live, journal, orb):
        app.include_router(module.router)

    @app.get("/api/health")
    def ok() -> dict:
        return {"ok": True}

    dist = static or dist_dir()
    if (dist / "index.html").exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist.resolve()):
                return FileResponse(file)
            return FileResponse(dist / "index.html")  # client-side routes
    else:

        @app.get("/", include_in_schema=False)
        def missing():
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm install && npm run build"},
                status_code=503,
            )

    return app
