from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from alembic.config import Config
from alembic import command
from app.db.init_db import init_database
from app.api.v1.auth import router as auth_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.admin import router as admin_router
from app.api.v1.family import router as family_router
from app.api.v1.provider import router as provider_router
from fastapi.staticfiles import StaticFiles
import os

# Define the lifespan of the application
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # 1. Startup Logic
#     print("Initializing Database...")
#     init_database()
    
#     print("Checking for database updates via Alembic...")
#     alembic_cfg = Config("alembic.ini")
#     command.upgrade(alembic_cfg, "head")
#     print("Database is up to date!")
    
#     yield  # Application is now running
    
#     # 2. Shutdown Logic (if any)
#     print("Shutting down...")

# Initialize FastAPI with the lifespan
app = FastAPI(
    title="FamilySide App API",
    description="Backend API for the FamilySide Mobile Application",
    version="1.0.0",
    # lifespan=lifespan
)

# Middleware to log every request
# @app.middleware("http")
# async def log_requests(request: Request, call_next):
#     response = await call_next(request)

#     print(f"[REQUEST] {request.method} {request.url.path} - Status: {response.status_code}")

#     return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

# Create the directory if it doesn't exist to prevent startup errors
if not os.path.exists("uploads"):
    os.makedirs("uploads")

# This allows you to visit http://localhost:8015/uploads/profiles/user_3.jpg
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(family_router, prefix="/api/v1")
app.include_router(provider_router, prefix="/api/v1")

@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "success",
        "message": "Welcome to FamilySide API. The server is up and running!"
    }