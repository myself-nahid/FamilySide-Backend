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