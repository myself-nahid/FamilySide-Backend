from pydantic import BaseModel
from typing import List, Optional

class HomeHeaderResponse(BaseModel):
    first_name: str
    location_name: str
    unread_notifications: int

class CategoryTab(BaseModel):
    id: int
    name: str

class HomeItemCard(BaseModel):
    id: int
    item_type: str
    name: str
    image_url: Optional[str]
    category_name: str
    price: float
    distance_km: Optional[float]
    age_range: str # Derived from tags
    date_label: Optional[str] # e.g. "25 Jun"
    is_recommended: bool
    is_saved: bool

class HomeFeedResponse(BaseModel):
    categories: List[CategoryTab]
    recommended: List[HomeItemCard]
    events_near_you: List[HomeItemCard]

class SubCategoryListResponse(BaseModel):
    id: int
    name: str
    image_url: Optional[str]
    description: Optional[str] = "Clinic / Center"

class SubCategoryItemsResponse(BaseModel):
    total_results: int
    items: List[HomeItemCard]

class SearchFilterParams(BaseModel):
    search: Optional[str] = None
    location_query: Optional[str] = None  # Text search for location name
    distance_range: Optional[str] = None  # "1km", "2-5km", etc.
    min_rating: Optional[float] = None    # 5, 4, 3
    categories: Optional[List[str]] = None # Multi-select categories
    child_age: Optional[str] = None       # "0-3 years", "3-8 years", etc.
    price_type: Optional[str] = "All"      # "All", "Free", "Paid"