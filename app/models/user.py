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
    
    # Onboarding Fields
    role = Column(String, nullable=True) # Mother, Father, Relative
    location_name = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    profile_image_url = Column(String, nullable=True)
    
    is_active = Column(Boolean, default=True)
    onboarding_completed = Column(Boolean, default=False)

    # Relationships
    children = relationship("Child", back_populates="parent", cascade="all, delete-orphan")
    interests = relationship("Interest", secondary=user_interests, back_populates="users")


class Child(Base):
    __tablename__ = 'children'
    
    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"))
    is_expecting = Column(Boolean, default=False)
    
    # If Kids
    name = Column(String, nullable=True)
    dob = Column(Date, nullable=True)
    gender = Column(String, nullable=True) # boy, girl, other
    
    # If Expecting
    expected_due_date = Column(Date, nullable=True)

    parent = relationship("User", back_populates="children")


class Interest(Base):
    __tablename__ = 'interests'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) # e.g., Education, Music, Sports

    users = relationship("User", secondary=user_interests, back_populates="interests")