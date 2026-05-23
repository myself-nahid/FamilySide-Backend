from click import command
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from alembic.config import Config
from alembic import command
from app.db.init_db import init_database, sync_database_schema
init_database()
from app.db.session import engine
from app.models import user
from app.api.v1.auth import router as auth_router
from app.api.v1.onboarding import router as onboarding_router

user.Base.metadata.create_all(bind=engine)
sync_database_schema(engine)

def run_migrations():
    print("Checking for database updates...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Database is up to date!")

run_migrations()

app = FastAPI(
    title="FamilySide App API",
    description="Backend API for the FamilySide Mobile Application",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "success",
        "message": "Welcome to FamilySide API. The server is up and running!"
    }