from sqlalchemy import Column, DateTime, Integer, String, Boolean, Date, Time, ForeignKey, Float, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.dialects.postgresql import JSONB

# TAXONOMY (Categories & Tags)
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True) 
    
    # Relationship to Sub-Categories
    sub_categories = relationship("SubCategory", back_populates="category", cascade="all, delete-orphan")

class SubCategory(Base):
    __tablename__ = "sub_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    image_url = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"))
    is_active = Column(Boolean, default=True)
    
    category = relationship("Category", back_populates="sub_categories")

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)


# PLATFORM ITEMS (Activities, Events, Gifts)
class PlatformItem(Base):
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
    
    # Activity specific
    opening_days = Column(String, nullable=True)
    opening_hours = Column(String, nullable=True)
    
    # Event / Gift Specific
    date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    
    # Taxonomy (JSON)
    sub_categories = Column(JSONB, nullable=True)
    tags = Column(JSONB, nullable=True)
    
    # Status Workflow
    status = Column(String, default="pending") 
    image_url = Column(String, nullable=True)
    created_at = Column(Date, default=func.now())

    creator = relationship("User", backref="created_items")
    category = relationship("Category")

    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True) # Receiver
    
    title = Column(String, nullable=False)    # e.g., "New Events added"
    subtitle = Column(String, nullable=False) # e.g., "A new music class is near you"
    
    item_type = Column(String, nullable=True) # activity, event, gift
    item_id = Column(Integer, nullable=True) 
    
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", backref="notifications")

class SavedItem(Base):
    __tablename__ = "saved_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    item_id = Column(Integer, ForeignKey("platform_items.id", ondelete="CASCADE"))
    gift_list_id = Column(Integer, ForeignKey("user_gift_lists.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    gift_list = relationship("UserGiftList", back_populates="saved_items")
    item = relationship("PlatformItem")

class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    item_id = Column(Integer, ForeignKey("platform_items.id", ondelete="CASCADE"))
    
    # Matching "Write Review" UI (Image 1)
    recommendation_level = Column(String) # Highly Recommended, Recommended, Average, Not suitable
    comment = Column(Text)
    category_name = Column(String) # Selected category for this review
    tags = Column(JSON) # e.g. ["Education", "Music"]
    
    image_url = Column(String, nullable=True) # Review photo
    created_at = Column(DateTime, default=func.now())

    user = relationship("User")
    item = relationship("PlatformItem", backref="item_reviews")

class UserGiftList(Base):
    __tablename__ = "user_gift_lists"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String, nullable=False) # e.g., "Emma's Birthday"
    occasion = Column(String, nullable=True) # e.g., "Birthday", "Christmas"
    description = Column(Text, nullable=True) # "Gift ideas Emma will love!"
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", backref="gift_folders")
    # Link to SavedItem table
    saved_items = relationship("SavedItem", back_populates="gift_list", cascade="all, delete-orphan")

class SupportMessage(Base):
    """Stores user queries from 'Contact Support' (Image 2)"""
    __tablename__ = "support_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    email = Column(String, nullable=False)
    location = Column(String, nullable=True)
    problem_details = Column(Text, nullable=False)
    status = Column(String, default="open") # open, resolved
    created_at = Column(DateTime, default=func.now())

    user = relationship("User")

class AnalyticsLog(Base):
    """Tracks every view/click for analytics generation"""
    __tablename__ = "analytics_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    item_id = Column(Integer, ForeignKey("platform_items.id", ondelete="CASCADE"), nullable=True)
    
    # Action types: 'profile_view', 'item_view', 'whatsapp_click', 'website_click'
    action_type = Column(String, nullable=False) 
    created_at = Column(DateTime, default=func.now())

    provider = relationship("User")