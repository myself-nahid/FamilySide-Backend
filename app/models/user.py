import datetime
from sqlalchemy.sql import func
from sqlalchemy import Column, Integer, String, Boolean, Date, ForeignKey, Float, Table
from sqlalchemy.orm import relationship
from app.db.session import Base

# Association table for User <-> Interest (Many-to-Many)
user_interests = Table(
    'user_interests',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('interest_id', Integer, ForeignKey('interests.id'), primary_key=True)
)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)
    auth_provider = Column(String, default="local")
    is_admin = Column(Boolean, default=False) # Only True for admin accounts
    
    # Distinguish between regular user and service provider 
    user_type = Column(String, default="family") # "family" or "provider"

    phone_number = Column(String, nullable=True)
    subscription_plan = Column(String, default="Free") # Free, Premium, Smart
    status = Column(String, default="Active") # Active, Suspended, Blocked
    join_date = Column(Date, default=func.now())
    
    # Shared Onboarding Fields
    location_name = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    profile_image_url = Column(String, nullable=True)
    
    # Family Specific
    role = Column(String, nullable=True) # Mother, Father, Relative
    
    is_active = Column(Boolean, default=True)
    onboarding_completed = Column(Boolean, default=False)

    # Relationships
    children = relationship("Child", back_populates="parent", cascade="all, delete-orphan")
    interests = relationship("Interest", secondary=user_interests, back_populates="users")
    
    # Provider Specific Relationship 
    social_links = relationship("SocialLink", back_populates="user", cascade="all, delete-orphan")

class OTPVerification(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True)
    email = Column(String, index=True)
    otp_code = Column(String)
    expires_at = Column(Date) # Or DateTime


class SocialLink(Base):
    __tablename__ = 'social_links'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"))
    platform = Column(String, nullable=False) # e.g., 'website', 'facebook', 'instagram'
    url = Column(String, nullable=False)
    
    user = relationship("User", back_populates="social_links")


class Child(Base):
    __tablename__ = 'children'
    
    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"))
    is_expecting = Column(Boolean, default=False)
    
    name = Column(String, nullable=True)
    dob = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    expected_due_date = Column(Date, nullable=True)

    parent = relationship("User", back_populates="children")


class Interest(Base):
    __tablename__ = 'interests'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    users = relationship("User", secondary=user_interests, back_populates="interests")