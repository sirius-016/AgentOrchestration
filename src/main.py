"""Application entry point."""

from fastapi import FastAPI
from src.api.routes import router

app = FastAPI(title="Agent Orchestration API")
app.include_router(router)
