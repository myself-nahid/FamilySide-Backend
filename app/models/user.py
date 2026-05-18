from sqlalchemy import Column, Integer, String, Boolean
from db.session import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)
    auth_provider = Column(String, default="local")
    
    is_active = Column(Boolean, default=True)
    onboarding_completed = Column(Boolean, default=False)