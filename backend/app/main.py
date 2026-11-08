from fastapi import FastAPI

from backend.app.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "phm"}
