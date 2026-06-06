from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class ProviderHomeHeader(BaseModel):
    name: str
    location: str
    unread_notifications: int

class ProviderItemCard(BaseModel):
    id: int
    name: str
    image_url: Optional[str]
    category_label: str # e.g., "Birthday"
    item_type: str     # activity, event
    price: float
    distance_km: float # Distance to the business center
    age_range: str
    date_label: Optional[str] # e.g., "25 June, 2026"

class ProviderHomeResponse(BaseModel):
    upcoming_events: List[ProviderItemCard]
    top_services: List[ProviderItemCard]

class AnalyticsDataPoint(BaseModel):
    label: str  # e.g., "Jan"
    value: float # e.g., 60.0 or -40.0

class ProviderAnalyticsResponse(BaseModel):
    category: str # "Profile Views", "User engagement", etc.
    year: int
    chart_data: List[AnalyticsDataPoint]
    suggestion_text: str # For the "Suggestions For You" pink card

class ContributorStats(BaseModel):
    reviews_count: int
    activities_count: int
    invited_family_count: int
    gifts_shared_count: int
    contributor_level: str # "Local Contributor"
    progress_percentage: float # 0.75 for the UI bar

class ProviderProfileResponse(BaseModel):
    name: str
    location: str
    image_url: Optional[str]
    stats: ContributorStats

class ManagedEventItem(BaseModel):
    id: int
    name: str
    item_type: str
    location: str
    date: str
    time: str
    image_url: Optional[str]

class ProviderEventsResponse(BaseModel):
    upcoming: List[ManagedEventItem]
    completed: List[ManagedEventItem]