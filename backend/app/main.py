from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from .routers import crowd
from .database import Base, engine, get_db
from .schemas import HealthResponse
from .routers import tracking
from .routers import bus
from .routers import prediction
from .routers import routes as routes_router

# Create database tables
Base.metadata.create_all(bind=engine)


# Create FastAPI application
app = FastAPI(
    title="Bus Crowd Intelligence API",
    description=(
        "Backend API for bus tracking, crowd monitoring, "
        "and bus fullness prediction."
    ),
    version="0.1.0",
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register routers
app.include_router(tracking.router)


@app.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """
    Check whether the API and database are working.
    """

    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "database": "connected",
        }

    except Exception:
        return {
            "status": "ok",
            "database": "error",
        }

app.include_router(crowd.router)
app.include_router(bus.router)
app.include_router(prediction.router)
app.include_router(routes_router.router)