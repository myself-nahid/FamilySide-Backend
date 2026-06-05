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