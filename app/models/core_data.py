from sqlalchemy import Column, DateTime, Integer, String, Boolean, Date, Time, ForeignKey, Float, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

class PlatformItem(Base):
    """Unified model for Activity, Event, and Gift"""
    __tablename__ = "platform_items"
    
    id = Column(Integer, primary_key=True, index=True)
    item_type = Column(String, nullable=False) # 'activity', 'event', 'gift'
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # Relationships
    creator_id = Column(Integer, ForeignKey("users.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))
    
    # Details
    location = Column(String, nullable=True)
    price = Column(Float, default=0.0)
    website = Column(String, nullable=True)
    email = Column(String, nullable=True)
    whatsapp = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    
    # Scheduling (Mainly for Events/Activities)
    date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    
    # Status Workflow (Crucial for Admin Dashboard)
    # Statuses: 'pending', 'approved', 'rejected', 'flagged', 'blocked'
    status = Column(String, default="pending") 
    image_url = Column(String, nullable=True)
    created_at = Column(Date, default=func.now())

    creator = relationship("User", backref="created_items")
    category = relationship("Category")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False) # e.g., "New Event Added"
    subtitle = Column(String, nullable=False) # e.g., "John Doe want to Join"
    
    # Polymorphic links
    item_type = Column(String, nullable=False) # 'activity', 'event', 'gift'
    item_id = Column(Integer, nullable=False) # Linked item's ID
    
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())