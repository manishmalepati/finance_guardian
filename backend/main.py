from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import agent, analytics, health, imports, transactions
from backend.common.exceptions import AppError, app_error_handler
from backend.db.session import init_database

app = FastAPI(title="Finance Guardian API", version="0.1.0")
app.add_exception_handler(AppError, app_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_database()


app.include_router(health.router)
app.include_router(imports.router, prefix="/imports", tags=["imports"])
app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(agent.router, prefix="/agent", tags=["agent"])
