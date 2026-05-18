from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.session import engine
from models import user
from api.v1.auth import router as auth_router

user.Base.metadata.create_all(bind=engine)

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

@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "success",
        "message": "Welcome to FamilySide API. The server is up and running!"
    }