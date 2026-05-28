from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import router
from storage.db import JobStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    await JobStore().init()
    yield


app = FastAPI(
    title="Ad Stack Competitive Analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
