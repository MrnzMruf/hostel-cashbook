from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.routers.api import router

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

app = FastAPI(
    title="Hostel Cashbook API",
    version="1.0.0",
    description="Daily income logging and cash / card / PMS reconciliation for a multi-channel hostel.",
)
app.include_router(router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND)
