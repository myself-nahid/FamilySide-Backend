import datetime  
from pydantic import BaseModel, EmailStr
from typing import List, Optional

class DashboardStatsResponse(BaseModel):
    pending_approvals: int
    flagged_reviews: int
    new_providers: int
    total_users: int

class UserActionRequest(BaseModel):
    action: str # "block", "suspend", "activate"

class ItemStatusUpdateRequest(BaseModel):
    status: str # "approved", "rejected", "blocked"

class CreateItemRequest(BaseModel):
    item_type: str # "activity", "event", "gift"
    name: str
    category_id: int
    location: str
    price: float
    description: str
    
    # Using datetime.date and datetime.time explicitly fixes the variable error
    date: Optional[datetime.date] = None
    start_time: Optional[datetime.time] = None
    end_time: Optional[datetime.time] = None
    
    website: Optional[str] = None
    whatsapp: Optional[str] = None
    instagram: Optional[str] = None

class AdminProfileUpdateRequest(BaseModel):
    name: str
    email: EmailStr
    phone_number: Optional[str] = None

# Add to app/schemas/admin_schema.py

class TrendMetric(BaseModel):
    count: int
    percentage_change: float  # e.g., 18.2
    is_increase: bool

class StatusDistribution(BaseModel):
    approved_pct: float
    pending_pct: float
    rejected_pct: float
    flagged_pct: float

class FlaggedItemListItem(BaseModel):
    id: int
    name: str
    item_type: str
    time_ago: str # e.g., "1 hr ago"

class PendingApprovalListItem(BaseModel):
    id: int
    name: str
    item_type: str

class UpcomingEventListItem(BaseModel):
    id: int
    name: str
    activity_id: Optional[int] = None
    image_url: Optional[str]
    date: str
    time: str

class DashboardOverviewResponse(BaseModel):
    # Top Row Cards
    pending_approvals: int
    flagged_reviews: int
    new_providers: int
    
    # Trend Cards (Comparing this week vs last week)
    total_users: TrendMetric
    new_users_this_week: TrendMetric
    activities: TrendMetric
    events: TrendMetric
    gifts: TrendMetric
    
    # Donut Chart
    status_distribution: StatusDistribution
    
    # Bottom Lists
    recent_flagged: List[FlaggedItemListItem]
    pending_todo: List[PendingApprovalListItem]
    upcoming_events: List[UpcomingEventListItem]

# Chart Schema
class ChartDataPoint(BaseModel):
    label: str  # e.g., "Jan", "Feb" or "Mon", "Tue"
    value: int

class ChartDataResponse(BaseModel):
    tab: str
    timeframe: str
    points: List[ChartDataPoint]

class ChildResponse(BaseModel):
    id: int
    name: str
    dob: str
    gender: str

class UserDetailResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: Optional[str] = "Parent"
    join_date: str
    location_name: Optional[str] = None
    status: str
    subscription_plan: str
    
    # Metrics seen on the Review Modal (Image 1)
    reviews_count: int
    activities_count: int
    saved_items_count: int
    contributor_level: str  # e.g., "Top 9%"
    
    # Nested Children List (Image 1)
    children: List[ChildResponse]

class NotificationItem(BaseModel):
    id: int
    title: str
    subtitle: str
    item_type: str
    item_id: int
    is_read: bool
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class ItemReviewDetailResponse(BaseModel):
    id: int
    item_type: str
    name: str
    activity_id: Optional[int] = None
    creator_email: Optional[str] = "abc@gmail.com"
    category: str
    category_id: Optional[int] = None
    sub_categories: Optional[List[str]] = []
    sub_category_ids: Optional[List[int]] = []
    tags: List[str] = []
    tag_ids: List[int] = []
    
    # Specific fields
    price: float
    includes: List[str] = []
    description: Optional[str] = None
    website: Optional[str] = None
    instagram_link: Optional[str] = None
    whatsapp_number: Optional[str] = None
    
    # Event specific
    date: Optional[str] = None
    time: Optional[str] = None
    
    # Activity specific
    opening_days: Optional[str] = "10:00 AM to 09:00 PM"
    opening_hours: Optional[str] = "10:00 AM to 09:00 PM"

class ActivityListItem(BaseModel):
    id: int
    name: str
    image_url: Optional[str]
    created_by: str   # e.g., "Provider", "User", "Admin"
    category: str
    location: str
    fee: float

class ActivityDetailResponse(BaseModel):
    id: int
    name: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    created_by: str
    status: str
    date_added: str
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    instagram: Optional[str] = None
    category: str
    category_id: Optional[int] = None
    sub_categories: Optional[List[str]] = []
    sub_category_ids: Optional[List[int]] = []
    tags: List[str] = []
    tag_ids: List[int] = []
    price: float
    opening_days: Optional[str] = None
    opening_hours: Optional[str] = None

class CreateActivityRequest(BaseModel):
    name: str
    location: str
    category_id: int
    price: float
    website: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    instagram: Optional[str] = None
    opening_days: Optional[str] = None
    opening_hours: Optional[str] = None
    description: str

class BulkDeleteRequest(BaseModel):
    ids: List[int]
class EventListItem(BaseModel):
    id: int
    name: str
    activity_id: Optional[int] = None
    image_url: Optional[str]
    created_by: str   
    category: str
    location: str
    fee: float

class EventDetailResponse(BaseModel):
    id: int
    name: str
    activity_id: Optional[int] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    created_by: str
    status: str
    date_added: str
    whatsapp: Optional[str] = None
    category: str
    category_id: Optional[int] = None
    sub_categories: Optional[List[str]] = []
    sub_category_ids: Optional[List[int]] = []
    tags: List[str] = []
    tag_ids: List[int] = []
    price: float = 0.0
    
    # Event Specifics
    date: Optional[str] = None
    time: Optional[str] = None

class GiftListItem(BaseModel):
    id: int
    name: str
    activity_id: Optional[int] = None
    image_url: Optional[str]
    created_by: str   
    category: str
    location: str
    fee: float
    includes: List[str] = []

class GiftDetailResponse(BaseModel):
    id: int
    name: str
    activity_id: Optional[int] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    created_by: str
    status: str
    date_added: str
    whatsapp: Optional[str] = None
    category: str
    category_id: Optional[int] = None
    sub_categories: Optional[List[str]] = []
    sub_category_ids: Optional[List[int]] = []
    tags: List[str] = []
    tag_ids: List[int] = []
    price: float = 0.0
    
    # Gift Specifics
    date: Optional[str] = None
    time: Optional[str] = None
    
    includes: List[str] = []

class GiftCardDesignItem(BaseModel):
    id: int
    image_url: str
    is_active: bool
    occasion: Optional[str] = None
    created_at: datetime.datetime

class GiftCardDesignDetailResponse(BaseModel):
    id: int
    image_url: str
    is_active: bool
    occasion: Optional[str] = None
    creator_id: Optional[int] = None
    created_at: datetime.datetime

class TaxonomyRequest(BaseModel):
    name: str

class SubCategoryRequest(BaseModel):
    name: str
    category_id: int

class TaxonomyResponseItem(BaseModel):
    id: int
    name: str
    is_active: bool
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    category_id: Optional[int] = None # Used for Sub-categories only
    category_name: Optional[str] = None # Used for Sub-categories only

class InterestRequest(BaseModel):
    name: str

class InterestResponseItem(BaseModel):
    id: int
    name: str

class AdminProfileUpdateRequest(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

class AIFlyerExtractionResponse(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None        # Format: DD/MM/YYYY
    start_time: Optional[str] = None  # Format: HH:MM AM/PM
    opening_days: Optional[str] = None
    opening_hours: Optional[str] = None
    location: Optional[str] = None
    price: Optional[float] = 0.0
    suggested_tags: List[str] = []

class GiftAIFlyerExtractionResponse(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = 0.0
    suggested_tags: List[str] = []

class AdminProfileResponse(BaseModel):
    name: str
    image_url: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

class LegalDocumentRequest(BaseModel):
    content: str

class LegalDocumentResponse(BaseModel):
    document_type: str
    content: str
    updated_at: Optional[datetime.datetime] = None

    class Config:
        orm_mode = True