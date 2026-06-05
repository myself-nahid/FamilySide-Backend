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

class MapPinResponse(BaseModel):
    id: int
    item_type: str
    lat: float
    lng: float
    category_icon: str # Derived from category

class ReviewResponse(BaseModel):
    user_name: str
    user_image: Optional[str]
    recommendation_level: str
    comment: str
    date: str

class ItemDetailFullResponse(BaseModel):
    id: int
    name: str
    description: str
    image_url: Optional[str]
    category_name: str
    lat: float
    lng: float
    address: str
    opening_hours: str
    website: Optional[str]
    instagram: Optional[str]
    whatsapp: Optional[str]
    
    # Nested components seen in Image 3
    related_events: List[HomeItemCard]
    gift_ideas: List[HomeItemCard]
    reviews: List[ReviewResponse]
    average_rating_label: str # e.g. "Recommended"

class GiftListCreate(BaseModel):
    name: str

class GiftListResponse(BaseModel):
    id: int
    name: str
    items_count: int

class SaveItemRequest(BaseModel):
    item_id: int
    gift_list_id: Optional[int] = None # If null, it goes to general bookmarks

class CategoryGridItem(BaseModel):
    id: int
    name: str
    image_url: Optional[str] = None # For the icons in the grid
    color_code: Optional[str] = None # e.g., "#E0F7FA" for the background

class SearchTabInitResponse(BaseModel):
    personalized_greeting: str # e.g., "For you, Mum"
    categories: List[CategoryGridItem]

class SearchHistoryResponse(BaseModel):
    recent_searches: List[str]

class NotificationItem(BaseModel):
    id: int
    title: str
    subtitle: str
    time_ago: str
    is_read: bool
    item_type: Optional[str]
    item_id: Optional[int]

class NotificationGroup(BaseModel):
    group_name: str # "Today", "This week", "Last month"
    notifications: List[NotificationItem]

class NotificationListResponse(BaseModel):
    unread_count: int
    groups: List[NotificationGroup]