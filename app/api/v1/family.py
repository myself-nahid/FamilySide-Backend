from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.core_data import LegalDocument, Notification, PlatformItem, Category, SavedItem, SubCategory, SupportMessage
from app.schemas.auth_schema import APIResponse
from app.schemas.family_schema import CategoryGridItem, FullProfileResponse, GiftFilterParams, HomeHeaderResponse, HomeItemCard, HomeFeedResponse, CategoryTab, ItemDetailFullResponse, MapPinResponse, MapItemResponse, NotificationGroup, NotificationItem, NotificationListResponse, ReviewResponse, SavedItemsResponse, SearchFilterParams, SearchTabInitResponse, SubCategoryListResponse, UserProfileMetrics, UserReviewItem
from app.models.core_data import UserGiftList, SavedItem
from app.schemas.family_schema import GiftListCreate, GiftListResponse, SaveItemRequest, GiftListFolderResponse, CreateGiftListRequest, AddToGiftListRequest
from app.models.core_data import Review
from app.models.core_data import SupportMessage, Review, PlatformItem
from app.schemas.family_schema import FullProfileResponse, UserProfileMetrics, ProfileUpdateRequest, SupportRequest, UserReviewItem
from app.schemas.family_schema import MyChildrenProfileResponse, ChildDetailInfo, UpdateChildrenProfileRequest
from app.core.utils import get_dynamic_time_ago
from app.models.user import Child
from datetime import datetime, timedelta
from app.core.utils import calculate_distance_km
from fastapi import Form, File, UploadFile
from app.models.core_data import Review
from app.models.core_data import AnalyticsLog
from app.core.utils import get_full_url
from app.core.config import settings
from jose import jwt, JWTError
import os
import shutil

from app.services.email_service import send_support_alert_to_admin

router = APIRouter(prefix="/family", tags=["Family App - Home"])

@router.get("/home/header", response_model=APIResponse[HomeHeaderResponse])
async def get_home_header(
    api_request: Request,         
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Matches Image 8: Returns Header stats and absolute Profile Image URL"""
    
    # 1. Calculate unread notifications
    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).count()
    
    # 2. Extract First Name
    first_name = current_user.full_name.split(" ")[0] if current_user.full_name else "Guest"
    
    # 3. Construct Absolute Image URL
    full_image_url = None
    if current_user.profile_image_url:
        # If it's already a full link (Social login)
        if current_user.profile_image_url.startswith("http"):
            full_image_url = current_user.profile_image_url
        else:
            # If it's a local path, use the 'api_request' we defined above
            base_url = str(api_request.base_url)
            if "localhost" in base_url or "127.0.0.1" in base_url:
                base_url = base_url.replace("https://", "http://") 
            full_image_url = f"{base_url}{current_user.profile_image_url.lstrip('/')}"

    return APIResponse(
        status="success", 
        message="Header loaded",
        data=HomeHeaderResponse(
            first_name=first_name,
            location_name=current_user.location_name or "Set location",
            unread_notifications=unread_count,
            profile_image_url=full_image_url
        )
    )

@router.get("/home/feed", response_model=APIResponse[HomeFeedResponse])
async def get_home_feed(
    api_request: Request,
    search: Optional[str] = None,         # From the Search Bar
    category_id: Optional[int] = None,    # From the Category Pill buttons
    sort_by: Optional[str] = "distance",  # Options: distance, price, newest
    limit: int = 10,                      # How many cards to show per section
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Advanced Data Engine: Extracts, filters, and sorts all Platform Items 
    to populate the Home Screen feeds accurately.
    """
    
    # 1. Fetch Categories for the horizontal scroll menu
    categories = db.query(Category).filter(Category.is_active == True).all()
    cat_tabs = [CategoryTab(id=c.id, name=c.name) for c in categories]
    
    # 2. Get user's saved items to highlight the bookmark icon
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]
    
    # 3. Base Query Engine (Only approved items)
    base_query = db.query(PlatformItem).filter(PlatformItem.status == "approved")
    
    # Apply Search Filter (Matches Name or Description)
    if search:
        base_query = base_query.filter(
            or_(
                PlatformItem.name.ilike(f"%{search}%"),
                PlatformItem.description.ilike(f"%{search}%")
            )
        )
        
    # Apply Category Filter
    if category_id:
        base_query = base_query.filter(PlatformItem.category_id == category_id)

    # 4. Helper Function to Process and Sort Data
    def process_and_sort_items(items, is_event=False):
        processed_list = []
        for item in items:
            absolute_image_url = get_full_url(api_request, item.image_url)
            dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
            
            # --- IMPROVED DATE LOGIC ---
            # If item has a specific date, use it. 
            # Fallback to created_at if no specific date is set.
            display_date = item.date or item.created_at
            date_label = display_date.strftime("%d %B, %Y") if display_date else None
            # ---------------------------

            age_range = "0-20 years"
            if item.tags and isinstance(item.tags, list):
                age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
                if age_tags: age_range = age_tags[0]

            card = HomeItemCard(
                id=item.id,
                item_type=item.item_type,
                name=item.name,
                image_url=absolute_image_url,
                category_name=item.category.name if item.category else "General",
                price=item.price or 0.0,
                distance_km=dist, # Will show a number if coordinates exist in DB
                age_range=age_range,
                date_label=date_label, # Now returns a string instead of null
                is_recommended=True,
                is_saved=(item.id in saved_item_ids)
            )
            
            processed_list.append({
                "card": card, 
                "raw_distance": dist if dist is not None else 9999.0,
                "raw_price": item.price or 0.0,
                "raw_date": item.created_at or datetime.min
            })
            
        # Apply Advanced Sorting
        if sort_by == "distance":
            processed_list.sort(key=lambda x: x["raw_distance"])
        elif sort_by == "price":
            processed_list.sort(key=lambda x: x["raw_price"])
        elif sort_by == "newest":
            processed_list.sort(key=lambda x: x["raw_date"], reverse=True)
            
        # Extract just the cards and apply the limit
        return [p["card"] for p in processed_list[:limit]]

    # 5. Execute Queries
    # Recommended For You (Activities)
    activities = base_query.filter(PlatformItem.item_type == "activity").all()
    recommended_cards = process_and_sort_items(activities, is_event=False)

    # Events Near You
    now = datetime.utcnow()
    # Events should strictly be in the future
    events = base_query.filter(
        and_(
            PlatformItem.item_type == "event",
            PlatformItem.date >= now.date()
        )
    ).all()
    event_cards = process_and_sort_items(events, is_event=True)

    # 6. Return Unified Payload
    return APIResponse(
        status="success", 
        message="Filtered and sorted feed loaded",
        data=HomeFeedResponse(
            categories=cat_tabs,
            recommended=recommended_cards,
            events_near_you=event_cards
        )
    )

# SEE ALL: RECOMMENDED ACTIVITIES
@router.get("/activities/recommended", response_model=APIResponse[dict])
async def get_all_recommended_activities(
    page: int = 1,
    limit: int = 10,
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Handles the 'See All' button for Recommended Activities with pagination"""
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]
    
    query = db.query(PlatformItem).filter(
        PlatformItem.status == "approved",
        PlatformItem.item_type == "activity"
    )
    
    if category_id: query = query.filter(PlatformItem.category_id == category_id)
    if search: query = query.filter(PlatformItem.name.ilike(f"%{search}%"))

    # Execute query
    items = query.all()
    
    # Process and calculate distance for all matching items
    processed_list = []
    for item in items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
            if age_tags: age_range = age_tags[0]

        card = HomeItemCard(
            id=item.id, item_type=item.item_type, name=item.name, image_url=item.image_url,
            category_name=item.category.name if item.category else "Uncategorized",
            price=item.price or 0.0, distance_km=dist, age_range=age_range, date_label=None,
            is_recommended=True, is_saved=(item.id in saved_item_ids)
        )
        processed_list.append({"card": card, "dist": dist if dist is not None else 9999.0})
    
    # Sort by distance
    processed_list.sort(key=lambda x: x["dist"])
    
    # Apply manual Pagination
    total_count = len(processed_list)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_cards = [p["card"] for p in processed_list[start_idx:end_idx]]

    return APIResponse(
        status="success", message="Recommended activities fetched",
        data={"total": total_count, "page": page, "limit": limit, "items": paginated_cards}
    )

# SEE ALL: EVENTS NEAR YOU
@router.get("/events/nearby", response_model=APIResponse[dict])
async def get_all_nearby_events(
    page: int = 1,
    limit: int = 10,
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Handles the 'See All' button for Events Near You with pagination"""
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]
    
    now = datetime.utcnow()
    query = db.query(PlatformItem).filter(
        PlatformItem.status == "approved",
        PlatformItem.item_type == "event",
        PlatformItem.date >= now.date()
    )
    
    if category_id: query = query.filter(PlatformItem.category_id == category_id)
    if search: query = query.filter(PlatformItem.name.ilike(f"%{search}%"))

    items = query.all()
    
    processed_list = []
    for item in items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
        card = HomeItemCard(
            id=item.id, item_type=item.item_type, name=item.name, image_url=item.image_url,
            category_name=item.category.name if item.category else "Event",
            price=item.price or 0.0, distance_km=dist, age_range="All ages", 
            date_label=item.date.strftime("%d %b") if item.date else None,
            is_recommended=True, is_saved=(item.id in saved_item_ids)
        )
        processed_list.append({"card": card, "dist": dist if dist is not None else 9999.0})
    
    # Sort by distance
    processed_list.sort(key=lambda x: x["dist"])
    
    # Apply manual Pagination
    total_count = len(processed_list)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_cards = [p["card"] for p in processed_list[start_idx:end_idx]]

    return APIResponse(
        status="success", message="Nearby events fetched",
        data={"total": total_count, "page": page, "limit": limit, "items": paginated_cards}
    )

# STEP 1: GET SUB-CATEGORIES FOR A CATEGORY 
@router.get("/categories/{category_id}/sub-categories", response_model=APIResponse[List[SubCategoryListResponse]])
async def get_sub_categories_for_family(
    api_request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    When user clicks 'Health' (ID: 1), this returns 'Pediatrician', 'Dentist', etc.
    """
    sub_cats = db.query(SubCategory).filter(
        SubCategory.category_id == category_id,
        SubCategory.is_active == True
    ).all()
    
    # In a real app, you might store an image_url on the SubCategory model. 
    # For now, we return the list.
    data = [
        SubCategoryListResponse(
            id=s.id,
            name=s.name,
            image_url=get_full_url(api_request, s.image_url) if s.image_url else None,
            description="Clinic / Center"
        ) for s in sub_cats
    ]
    
    return APIResponse(status="success", message="Sub-categories loaded", data=data)


# STEP 2: GET ITEMS BY SUB-CATEGORY 
@router.get("/sub-categories/{sub_category_name}/items", response_model=APIResponse[dict])
async def get_items_by_sub_category(
    sub_category_name: str,
    item_type: str = "activity",  # 'activity' or 'event' based on Image 2 tabs
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    When user clicks 'Pediatrician', this returns the list of specific Clinics.
    """
    # 1. Get user's saved items for the bookmark icon
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]
    
    # 2. Query Platform Items
    # Note: We filter by the sub_category name stored inside the JSON column 'sub_categories'
    query = db.query(PlatformItem).filter(
        PlatformItem.status == "approved",
        PlatformItem.item_type == item_type,
        # This tells Postgres: "Does this JSONB array contain the string 'Pediatrician'?"
        PlatformItem.sub_categories.contains([sub_category_name]) 
    )
    
    total_results = query.count()
    raw_items = query.all()
    
    # 3. Process and Calculate Distances
    processed_list = []
    for item in raw_items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower()]
            if age_tags: age_range = age_tags[0]

        card = HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=item.image_url,
            category_name=item.category.name if item.category else "Health",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=age_range,
            date_label=item.date.strftime("%d %b") if item.date else None,
            is_recommended=(item.status == "approved"), # Logic for recommended badge
            is_saved=(item.id in saved_item_ids)
        )
        processed_list.append({"card": card, "dist": dist if dist is not None else 9999.0})

    # 4. Sort by distance (Nearest first)
    processed_list.sort(key=lambda x: x["dist"])
    
    # 5. Apply Pagination
    start = (page - 1) * limit
    end = start + limit
    paginated_data = [p["card"] for p in processed_list[start:end]]

    return APIResponse(
        status="success", 
        message=f"{item_type.capitalize()} results for {sub_category_name}",
        data={
            "total_results": total_results,
            "page": page,
            "items": paginated_data
        }
    )


@router.get("/items/search", response_model=APIResponse[dict])
async def search_and_filter_items(
    api_request: Request,
    # Use Depends for complex query parameters
    params: SearchFilterParams = Depends(),
    item_type: str = "activity", 
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Base Query
    query = db.query(PlatformItem).filter(
        PlatformItem.status == "approved",
        PlatformItem.item_type == item_type
    )

    # 2. Additive Filters (Applying logic from both Modals)
    
    # Text Search (Name or Description)
    if params.search:
        query = query.filter(PlatformItem.name.ilike(f"%{params.search}%"))

    # Location Name Search (Modal 2)
    if params.location_query:
        query = query.filter(PlatformItem.location.ilike(f"%{params.location_query}%"))

    # Multi-select Categories (Modal 2)
    if params.categories:
        # Check if the JSONB sub_categories list contains any of the selected categories
        # Logic: Does the item have at least one of the selected category tags?
        query = query.filter(PlatformItem.sub_categories.has_any(params.categories))

    # Price Filter (Modal 2)
    if params.price_type == "Free":
        query = query.filter(PlatformItem.price == 0)
    elif params.price_type == "Paid":
        query = query.filter(PlatformItem.price > 0)

    # 3. Post-Processing (Distance & Age Logic)
    # We fetch results to calculate distance in Python (standard for MVP/Low volume)
    raw_items = query.all()
    processed_list = []

    for item in raw_items:
        absolute_image_url = get_full_url(api_request, item.image_url)
        # A. Calculate Distance
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        display_date = item.date or item.created_at
        date_label = display_date.strftime("%d %B, %Y") if display_date else None
        
        # Filter by Distance Range (Modal 1)
        if params.distance_range:
            if params.distance_range == "1km" and (dist is None or dist > 1): continue
            if params.distance_range == "2-5km" and (dist is None or not (2 <= dist <= 5)): continue
            if params.distance_range == "6-10km" and (dist is None or not (6 <= dist <= 10)): continue
            if params.distance_range == "10+km" and (dist is None or dist < 10): continue

        # B. Filter by Child Age (Modal 1 & 2)
        # We look inside the JSONB 'tags' column for the age string
        if params.child_age:
            if not item.tags or params.child_age not in item.tags:
                continue

        # C. Filter by Review Rating (Modal 1)
        # Assuming you have a 'rating' column (if not, use mock/average)
        item_rating = getattr(item, 'average_rating', 5.0) 
        if params.min_rating:
            if params.min_rating == 3 and item_rating < 3: continue
            if params.min_rating > 3 and item_rating < params.min_rating: continue

        # Construct Card
        card = HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=absolute_image_url,
            category_name=item.category.name if item.category else "General",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=params.child_age or "0-20 years",
            date_label=date_label,
            is_recommended=True,
            is_saved=False # Check against SavedItem table here
        )
        processed_list.append({"card": card, "dist": dist if dist is not None else 9999.0})

    # 4. Sort results (Default by nearest)
    processed_list.sort(key=lambda x: x["dist"])
    
    # 5. Pagination
    total_results = len(processed_list)
    start = (page - 1) * limit
    paginated_items = [p["card"] for p in processed_list[start : start + limit]]

    return APIResponse(
        status="success", 
        message="Filtered results fetched",
        data={"total": total_results, "items": paginated_items}
    )


# 1. MAP DISCOVERY 
@router.get("/explore/map", response_model=APIResponse[dict])
async def get_map_pins(
    api_request: Request,
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    categories = db.query(Category).filter(Category.is_active == True).all()
    category_list = [CategoryTab(id=c.id, name=c.name) for c in categories]

    query = db.query(PlatformItem).filter(PlatformItem.status == "approved")
    if category_id:
        query = query.filter(PlatformItem.category_id == category_id)
    items = query.all()

    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]

    pins = [
        MapPinResponse(
            id=i.id,
            item_type=i.item_type,
            lat=i.lat or 0.0,
            lng=i.lng or 0.0,
            category_icon=i.category.name if i.category else "General"
        ) for i in items if i.lat is not None and i.lng is not None
    ]

    map_items = []
    for item in items:
        map_items.append(MapItemResponse(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_name=item.category.name if item.category else "General",
            price=item.price or 0.0,
            lat=item.lat or 0.0,
            lng=item.lng or 0.0,
            location=item.location or "N/A",
            distance_km=calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng),
            age_range="0-20 years",
            date_label=item.date.strftime("%d %B %Y") if item.date else None,
            is_recommended=True,
            is_saved=(item.id in saved_item_ids)
        ))

    return APIResponse(
        status="success",
        message="Map data loaded",
        data={
            "categories": category_list,
            "items": map_items,
            "pins": pins
        }
    )

# Define the helper function 
def log_analytics(db: Session, provider_id: int, action: str, item_id: int = None):
    """Saves a record of a user interaction for the analytics chart"""
    log = AnalyticsLog(provider_id=provider_id, action_type=action, item_id=item_id)
    db.add(log)
    db.commit()

# 2. ITEM FULL DETAILS 
@router.get("/items/{item_id}/details", response_model=APIResponse[ItemDetailFullResponse])
async def get_item_details(item_id: int, api_request: Request, db: Session = Depends(get_db)):
    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Every time this API is called, we log an 'item_view' for the provider
    if item.creator_id:
        log_analytics(
            db,
            provider_id=item.creator_id,
            action="item_view",
            item_id=item.id
        )

    # Fetch nested lists for the detail page
    events = db.query(PlatformItem).filter(
        PlatformItem.item_type == "event",
        PlatformItem.category_id == item.category_id,
        PlatformItem.id != item.id,
        PlatformItem.status == "approved"
    ).limit(3).all()

    gifts = db.query(PlatformItem).filter(
        PlatformItem.item_type == "gift",
        PlatformItem.status == "approved"
    ).limit(3).all()

    reviews = db.query(Review).filter(Review.item_id == item_id).order_by(Review.created_at.desc()).limit(5).all()

    # Map events and gifts into HomeItemCard-like responses
    def map_to_card(src_item):
        return HomeItemCard(
            id=src_item.id,
            item_type=src_item.item_type,
            name=src_item.name,
            image_url=get_full_url(api_request, src_item.image_url) if src_item.image_url else None,
            category_name=src_item.category.name if src_item.category else "General",
            price=src_item.price or 0.0,
            distance_km=None,
            age_range="0-20 years",
            date_label=src_item.date.strftime("%d %B %Y") if src_item.date else None,
            is_recommended=(src_item.status == "approved"),
            is_saved=False
        )

    related_events = [map_to_card(e) for e in events]
    gift_ideas = [map_to_card(g) for g in gifts]

    # Formatted Response
    data = ItemDetailFullResponse(
        id=item.id,
        name=item.name,
        description=item.description or "",
        image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
        category_name=item.category.name if item.category else "Playground",
        lat=item.lat or 0.0,
        lng=item.lng or 0.0,
        address=item.location or "N/A",
        opening_hours=item.opening_hours or "07:00 AM to 09:00 PM",
        website=item.website,
        instagram=item.instagram,
        whatsapp=item.whatsapp,
        related_events=related_events,
        gift_ideas=gift_ideas,
        reviews=[
            ReviewResponse(
                user_name=r.user.full_name if r.user else "",
                user_image=r.user.profile_image_url if r.user else None,
                recommendation_level=r.recommendation_level,
                comment=r.comment,
                date=r.created_at.strftime("%d %B %Y")
            ) for r in reviews
        ],
        average_rating_label="Recommended"
    )
    return APIResponse(status="success", message="Details loaded", data=data)


# 4. SHARE ITEM (Generate a short, signed link that can be shared externally)
@router.post("/items/{item_id}/share", response_model=APIResponse[dict])
async def share_item(
    item_id: int,
    api_request: Request,
    expire_hours: int = 168,  # default 7 days
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.utcnow()
    exp = now + timedelta(hours=expire_hours)
    payload = {
        "item_id": item.id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "shared_by": current_user.id
    }

    token = jwt.encode(payload, settings.SECRET_KEY or "", algorithm=settings.ALGORITHM or "HS256")
    # Ensure the generated URL points to the publicly resolvable route (includes API prefix)
    share_url = f"{str(api_request.base_url).rstrip('/')}/api/v1/family/share/item/{token}"

    return APIResponse(status="success", message="Share link generated", data={"share_url": share_url, "expires_at": int(exp.timestamp())})


# Resolve share token and return public item summary
@router.get("/share/item/{token}", response_model=APIResponse[dict])
async def resolve_share_token(token: str, api_request: Request, db: Session = Depends(get_db)):
    try:
        data = jwt.decode(token, settings.SECRET_KEY or "", algorithms=[settings.ALGORITHM or "HS256"])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired share token")

    item_id = data.get("item_id")
    if not item_id:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Return a compact public summary (suitable for share preview)
    public = {
        "id": item.id,
        "name": item.name,
        "description": item.description or "",
        "image_url": get_full_url(api_request, item.image_url) if item.image_url else None,
        "category_name": item.category.name if item.category else "",
        "price": item.price or 0.0,
        "lat": item.lat or 0.0,
        "lng": item.lng or 0.0,
        "address": item.location or "",
        "status": item.status
    }

    return APIResponse(status="success", message="Share token resolved", data=public)

# 3. WRITE REVIEW 
@router.post("/items/{item_id}/reviews", response_model=APIResponse[None])
async def post_item_review(
    item_id: int,
    recommendation_level: str = Form(...), # Still required
    comment: str = Form(...),              # Still required
    category_name: Optional[str] = Form(None), # <--- CHANGED: Now optional
    tags: Optional[str] = Form(None), 
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    import json
    
    # 1. Check if the item exists
    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. Handle File Upload
    saved_path = None
    if photo and photo.filename:
        os.makedirs("uploads/reviews", exist_ok=True)
        saved_path = f"uploads/reviews/{datetime.utcnow().timestamp()}_{photo.filename}"
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)

    # 3. Robust Tag Parsing
    parsed_tags = []
    if tags:
        try:
            parsed_tags = json.loads(tags)
        except:
            parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    # 4. Save to Database
    new_review = Review(
        user_id=current_user.id,
        item_id=item_id,
        category_name=category_name, # Will save as NULL if not provided
        recommendation_level=recommendation_level,
        comment=comment,
        tags=parsed_tags,
        image_url=f"/{saved_path}" if saved_path else None
    )
    
    # 5. Notify Provider (logic we added previously)
    if item.creator_id:
        review_notif = Notification(
            user_id=item.creator_id,
            title="New Review Received! ⭐",
            subtitle=f"{current_user.full_name} left a review on '{item.name}'.",
            item_type=item.item_type,
            item_id=item.id,
            is_read=False
        )
        db.add(review_notif)

    db.add(new_review)
    db.commit()
    
    return APIResponse(status="success", message="Review submitted successfully!")

# 1. SEARCH & EXPLORE ENGINE 
@router.get("/explore/list", response_model=APIResponse[dict])
async def explore_items_list(
    item_type: str = "activity", # activity, event, gift
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    # Filter Params from Modals (Images 2 & 5)
    max_distance: Optional[float] = None,
    min_rating: Optional[float] = None,
    child_age: Optional[str] = None,
    price_type: str = "All",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Powerful extraction engine that powers the 'Explore' tabs.
    Calculates distance and filters by age/price/rating dynamically.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "approved", PlatformItem.item_type == item_type)
    
    if category_id: query = query.filter(PlatformItem.category_id == category_id)
    if search: query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
    if price_type == "Free": query = query.filter(PlatformItem.price == 0)
    elif price_type == "Paid": query = query.filter(PlatformItem.price > 0)

    raw_items = query.all()
    processed_cards = []
    
    # User's saved item IDs for the bookmark icon state
    user_saved_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]

    for item in raw_items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
        # UI Filters
        if max_distance and (dist is None or dist > max_distance): continue
        if child_age and (not item.tags or child_age not in item.tags): continue

        processed_cards.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=item.image_url,
            category_name=item.category.name if item.category else "Health",
            price=item.price,
            distance_km=dist,
            age_range=child_age or "0-20 years",
            date_label=item.date.strftime("%d %b") if item.date else None,
            is_recommended=True,
            is_saved=(item.id in user_saved_ids)
        ))

    # Sort by Distance
    processed_cards.sort(key=lambda x: x.distance_km if x.distance_km is not None else 999)

    return APIResponse(status="success", message="Results loaded", data={"items": processed_cards})


# 2. GIFT LIST MANAGEMENT 
@router.get("/gift-lists", response_model=APIResponse[List[GiftListResponse]])
async def get_my_gift_lists(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetches user's custom lists (Birthday, Anniversary, etc.)"""
    lists = db.query(UserGiftList).filter(UserGiftList.user_id == current_user.id).all()
    
    # If user is new, seed the default lists seen in Image 7
    if not lists:
        for name in ["Birthday", "Anniversary", "Special", "General"]:
            db.add(UserGiftList(user_id=current_user.id, name=name))
        db.commit()
        lists = db.query(UserGiftList).filter(UserGiftList.user_id == current_user.id).all()

    data = [GiftListResponse(id=l.id, name=l.name, items_count=len(l.items)) for l in lists]
    return APIResponse(status="success", message="Lists fetched", data=data)


@router.post("/saved-items/toggle", response_model=APIResponse[dict])
async def toggle_save_item(
    payload: SaveItemRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Handles clicking the bookmark icon or the 'Add to Gift List' button"""
    existing = db.query(SavedItem).filter(
        SavedItem.user_id == current_user.id, 
        SavedItem.item_id == payload.item_id,
        SavedItem.gift_list_id == payload.gift_list_id
    ).first()

    if existing:
        db.delete(existing)
        message = "Removed from list"
        is_saved = False
    else:
        new_save = SavedItem(
            user_id=current_user.id, 
            item_id=payload.item_id, 
            gift_list_id=payload.gift_list_id
        )
        db.add(new_save)
        message = "Saved to list"
        is_saved = True
    
    db.commit()
    return APIResponse(status="success", message=message, data={"is_saved": is_saved})


@router.post("/saved-items/universal_toggle", response_model=APIResponse[dict])
async def toggle_save_item(
    payload: SaveItemRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    UNIVERSAL SAVE ENDPOINT: 
    Handles saving/unsaving Activities, Events, and Gifts based purely on item_id.
    """
    # 1. Fetch the Item to verify it exists and find out what TYPE it is
    item = db.query(PlatformItem).filter(PlatformItem.id == payload.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Format the item type for friendly UI messages (e.g. "Activity", "Event", "Gift")
    i_type = item.item_type.capitalize()

    # 2. Check if the User Gift List folder exists (if provided)
    if payload.gift_list_id:
        g_list = db.query(UserGiftList).filter(
            UserGiftList.id == payload.gift_list_id, 
            UserGiftList.user_id == current_user.id
        ).first()
        if not g_list:
            raise HTTPException(status_code=404, detail="Gift list folder not found")

    # 3. Check if the item is already saved by this user
    existing_save = db.query(SavedItem).filter(
        SavedItem.user_id == current_user.id, 
        SavedItem.item_id == payload.item_id
    ).first()

    if existing_save:
        # A. If they provided a list ID, they are moving it to a specific folder
        if payload.gift_list_id and existing_save.gift_list_id != payload.gift_list_id:
            existing_save.gift_list_id = payload.gift_list_id
            message = f"{i_type} moved to folder"
            is_saved = True
        # B. If they just clicked the bookmark icon, REMOVE IT (Unsave)
        else:
            db.delete(existing_save)
            message = f"{i_type} removed from saved items"
            is_saved = False
    else:
        # C. It's not saved yet, so SAVE IT universally
        new_save = SavedItem(
            user_id=current_user.id, 
            item_id=payload.item_id, 
            gift_list_id=payload.gift_list_id # Can be None for general save
        )
        db.add(new_save)
        message = f"{i_type} saved successfully"
        is_saved = True
    
    db.commit()
    
    # Return the status and explicitly tell the frontend what type was just saved
    return APIResponse(
        status="success", 
        message=message, 
        data={"is_saved": is_saved, "item_type": item.item_type}
    )


# 1. SEARCH TAB INITIALIZATION 
@router.get("/search/init", response_model=APIResponse[SearchTabInitResponse])
async def init_search_tab(
    api_request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Loads the initial Search screen:
    - Dynamic greeting (e.g. 'For you, Mum')
    - The Category Grid
    """
    # Dynamic greeting based on Role selected during onboarding
    role_label = current_user.role if current_user.role else "Parent"
    greeting = f"For you, {role_label}"

    # Fetch all active categories for the grid
    categories = db.query(Category).filter(Category.is_active == True).all()
    
    # Mocking colors for the UI grid as seen in Image 1
    ui_colors = ["#E0F7FA", "#E3F2FD", "#FCE4EC", "#E8F5E9", "#FFF3E0", "#FFFDE7"]
    
    category_list = []
    for idx, cat in enumerate(categories):
        category_list.append(CategoryGridItem(
            id=cat.id,
            name=cat.name,
            image_url=get_full_url(api_request, cat.image_url) if cat.image_url else None,
            color_code=ui_colors[idx % len(ui_colors)]
        ))

    return APIResponse(
        status="success", 
        message="Search screen initialized",
        data=SearchTabInitResponse(
            personalized_greeting=greeting,
            categories=category_list
        )
    )

# 2. UNIVERSAL SEARCH ENGINE (Handles Bar, Filters, and Quick Links)
@router.get("/search/execute", response_model=APIResponse[dict])
async def execute_search(
    api_request: Request, 
    q: Optional[str] = Query(None, alias="query"), 
    mode: Optional[str] = "all",                 
    category_id: Optional[int] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    The main engine for finding content.
    It processes the Search Bar, the 4 Quick Link cards, and Category taps.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "approved")

    # A. Handle Search Bar Text
    if q:
        query = query.filter(
            or_(
                PlatformItem.name.ilike(f"%{q}%"),
                PlatformItem.description.ilike(f"%{q}%")
            )
        )

    # B. Handle Quick Action Modes
    if mode == "gifts":
        query = query.filter(PlatformItem.item_type == "gift")
    elif mode == "events":
        query = query.filter(PlatformItem.item_type == "event")
    elif mode == "for_you":
        # Logic: Filter by user interests set during onboarding
        user_interest_names = [i.name for i in current_user.interests]
        if user_interest_names:
            tag_conditions = [PlatformItem.tags.contains([interest]) for interest in user_interest_names]
            query = query.filter(or_(*tag_conditions))
            
    # C. Handle Category Grid Taps
    if category_id:
        query = query.filter(PlatformItem.category_id == category_id)

    # D. Fetch and Process results
    raw_results = query.all()
    processed_cards = []
    
    # Get user's saved items to highlight the bookmark icon
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]

    for item in raw_results:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
        # If user clicked 'Near You', exclude items further than 50km
        if mode == "near_you" and (dist is None or dist > 50):
            continue

        display_date = item.date or item.created_at
        formatted_date = display_date.strftime("%d %B, %Y") if display_date else None
        
        absolute_image_url = get_full_url(api_request, item.image_url)

        processed_cards.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=absolute_image_url,
            category_name=item.category.name if item.category else "General",
            price=item.price or 0.0,
            distance_km=dist,
            age_range="0-20 years",
            date_label=formatted_date, 
            is_recommended=True,
            is_saved=(item.id in saved_item_ids)
        ))

    # E. Sorting
    if mode == "near_you":
        processed_cards.sort(key=lambda x: x.distance_km if x.distance_km is not None else 9999)
    else:
        processed_cards.sort(key=lambda x: x.id, reverse=True) # Newest first

    # F. Pagination
    start = (page - 1) * limit
    paginated_data = processed_cards[start : start + limit]

    return APIResponse(
        status="success",
        message="Search results fetched",
        data={"total": len(processed_cards), "items": paginated_data}
    )

"""
Notificfations
"""
# Helper to format time
def get_time_ago(dt: datetime):
    now = datetime.utcnow()
    diff = now - dt
    if diff.days == 0:
        if diff.seconds < 3600: return f"{diff.seconds // 60}min ago"
        return f"{diff.seconds // 3600}h ago"
    if diff.days < 7: return f"{diff.days} days ago"
    return dt.strftime("%d %b")

@router.get("/notifications", response_model=APIResponse[NotificationListResponse])
async def get_user_notifications(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Fetches and groups notifications (Today, Week, Month) as seen in UI"""
    
    notifications = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).all()

    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).count()

    # Initialize buckets
    today_items = []
    week_items = []
    month_items = []

    now = datetime.utcnow()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = now - timedelta(days=7)

    for n in notifications:
        item = NotificationItem(
            id=n.id,
            title=n.title,
            subtitle=n.subtitle,
            time_ago=get_time_ago(n.created_at),
            is_read=n.is_read,
            item_type=n.item_type,
            item_id=n.item_id
        )

        if n.created_at >= start_of_today:
            today_items.append(item)
        elif n.created_at >= start_of_week:
            week_items.append(item)
        else:
            month_items.append(item)

    # Build Response Groups
    groups = []
    if today_items: groups.append(NotificationGroup(group_name="Today", notifications=today_items))
    if week_items: groups.append(NotificationGroup(group_name="This week", notifications=week_items))
    if month_items: groups.append(NotificationGroup(group_name="Last month", notifications=month_items))

    return APIResponse(
        status="success", 
        message="Notifications loaded",
        data=NotificationListResponse(unread_count=unread_count, groups=groups)
    )

@router.patch("/notifications/mark-all-read", response_model=APIResponse[None])
async def mark_all_notifications_read(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return APIResponse(status="success", message="All notifications marked as read")

"""Gift Planner"""

# 1. GIFT PLANNER SEARCH 
@router.get("/gifts/search", response_model=APIResponse[dict])
async def search_gift_planner(
    api_request: Request,
    q: Optional[str] = Query(None, alias="query"),
    category: Optional[str] = "All", # Birthday, Christmas, etc.
    filters: GiftFilterParams = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Powerful search engine for the Gift Planner.
    Handles occasion tabs and the complex Filter Modal (Image 4).
    """
    query = db.query(PlatformItem).filter(PlatformItem.item_type == "gift", PlatformItem.status == "approved")

    # Filter by Occasion Tab
    if category != "All":
        query = query.filter(PlatformItem.tags.contains([category]))

    # Filter by Search Bar
    if q:
        query = query.filter(PlatformItem.name.ilike(f"%{q}%"))

    # Apply Modal Filters (Image 4)
    if filters.recipient:
        query = query.filter(PlatformItem.tags.contains([filters.recipient]))
    if filters.for_whom:
        query = query.filter(PlatformItem.tags.contains([filters.for_whom]))
    if filters.child_age:
        query = query.filter(PlatformItem.tags.contains([filters.child_age]))

    # Price Range Logic
    if filters.price_range == "Under $25":
        query = query.filter(PlatformItem.price < 25)
    elif filters.price_range == "$25 - $50":
        query = query.filter(and_(PlatformItem.price >= 25, PlatformItem.price <= 50))

    results = query.all()
    saved_item_ids = [s.item_id for s in db.query(SavedItem).filter(SavedItem.user_id == current_user.id).all()]
    categories = [
        CategoryTab(id=c.id, name=c.name)
        for c in db.query(Category).filter(Category.is_active == True).all()
    ]

    items = []
    for item in results:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
            if age_tags:
                age_range = age_tags[0]

        display_date = item.date or item.created_at
        items.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_name=item.category.name if item.category else "General",
            location=item.location or "N/A",
            price=item.price or 0.0,
            distance_km=dist if dist is not None else 0.0,
            age_range=age_range,
            date_label=display_date.strftime("%d %B %Y") if display_date else "",
            is_recommended=True,
            is_saved=(item.id in saved_item_ids)
        ))

    return APIResponse(
        status="success",
        message="Gifts found",
        data={"items": items, "categories": categories}
    )


# 2. MY GIFT LISTS / FOLDERS 
@router.get("/gift-planner/folders", response_model=APIResponse[dict])
async def get_my_gift_folders(
    api_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetches the folder overview (Emma's Birthday, etc.) seen in Image 2"""
    
    folders = db.query(UserGiftList).filter(UserGiftList.user_id == current_user.id).all()
    
    # Gifts saved but not in a folder
    loose_saved_items = db.query(SavedItem).join(PlatformItem, SavedItem.item_id == PlatformItem.id).filter(
        SavedItem.user_id == current_user.id,
        SavedItem.gift_list_id == None,
        PlatformItem.item_type == "gift"
    ).all()

    loose_items = len(loose_saved_items)
    loose_items_cards = []
    for saved_item in loose_saved_items:
        item = saved_item.item
        if not item:
            continue

        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
            if age_tags:
                age_range = age_tags[0]

        loose_items_cards.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_name=item.category.name if item.category else "General",
            location=item.location or "N/A",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=age_range,
            date_label=item.date.strftime("%d %B %Y") if item.date else None,
            is_recommended=True,
            is_saved=True
        ))

    # data = [
    #     GiftListFolderResponse(
    #         id=f.id, name=f.name, occasion=f.occasion or "General",
    #         items_count=len(f.saved_items),
    #         image_url=get_full_url(api_request, f.image_url) if f.image_url else None,
    #         last_updated_label="Last updated 2 days ago"
    #     ) for f in folders
    # ]
    data = []
    for f in folders:
        # Generate the dynamic label using our helper
        time_label = f"Last updated {get_dynamic_time_ago(f.updated_at)}"
        
        data.append(GiftListFolderResponse(
            id=f.id, 
            name=f.name, 
            occasion=f.occasion or "General",
            items_count=len(f.saved_items),
            image_url=get_full_url(api_request, f.image_url) if f.image_url else None,
            last_updated_label=time_label 
        ))
    
    return APIResponse(
        status="success",
        message="Folders loaded",
        data={
            "folders": data,
            "folders_count": len(data),
            "loose_items_count": loose_items,
            "loose_items": loose_items_cards
        }
    )


# 3. FOLDER DETAIL VIEW 
@router.get("/gift-planner/folders/{folder_id}")
async def get_folder_details(
    folder_id: int,
    api_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns items inside a specific folder like 'Emma's Birthday'"""
    folder = db.query(UserGiftList).filter(UserGiftList.id == folder_id, UserGiftList.user_id == current_user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    items = []
    for saved_item in folder.saved_items:
        item = saved_item.item
        if not item:
            continue

        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
            if age_tags:
                age_range = age_tags[0]

        items.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_name=item.category.name if item.category else "General",
            location=item.location or "N/A",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=age_range,
            date_label=item.date.strftime("%d %B %Y") if item.date else None,
            is_recommended=True,
            is_saved=True
        ))

    return APIResponse(status="success", message="Folder items loaded", data={"name": folder.name, "items": items})


# 4. CREATE NEW LIST & ADD ITEM 
@router.post("/gift-planner/folders", response_model=APIResponse[None])
async def create_new_gift_folder(
    name: str = Form(...),
    occasion: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Creates a new gift list/folder and handles optional cover image upload"""
    
    saved_image_path = None
    
    # 1. Handle File Upload if provided
    if photo and photo.filename:
        UPLOAD_DIR = "uploads/gift_lists"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        file_extension = photo.filename.split(".")[-1]
        file_name = f"list_{current_user.id}_{datetime.utcnow().timestamp()}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
            
        # Format the path with forward slashes for the database
        saved_image_path = f"/{file_path}".replace("\\", "/")

    # 2. Save to Database
    new_folder = UserGiftList(
        user_id=current_user.id, 
        name=name, 
        occasion=occasion,
        image_url=saved_image_path # Save the image URL
    )
    
    db.add(new_folder)
    db.commit()
    
    return APIResponse(status="success", message="List created successfully")

# delete individual item from folder
@router.delete("/gift-planner/folders/{folder_id}/items/{item_id}", response_model=APIResponse[None])
async def remove_item_from_folder(folder_id: int, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Removes an item from a specific gift folder"""
    saved_item = db.query(SavedItem).filter(SavedItem.gift_list_id == folder_id, SavedItem.item_id == item_id, SavedItem.user_id == current_user.id).first()
    
    if not saved_item:
        raise HTTPException(status_code=404, detail="Item not found in the specified folder")

    db.delete(saved_item)
    db.commit()
    
    return APIResponse(status="success", message="Item removed from folder")

@router.post("/gift-planner/add-to-folder", response_model=APIResponse[None])
async def add_item_to_folder(payload: AddToGiftListRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Matches Image 5 Modal: Moves an item into a specific folder"""
    saved_item = db.query(SavedItem).filter(SavedItem.item_id == payload.item_id, SavedItem.user_id == current_user.id).first()
    
    if not saved_item:
        # If not bookmarked yet, create a new saved entry
        saved_item = SavedItem(user_id=current_user.id, item_id=payload.item_id)
        db.add(saved_item)

    saved_item.gift_list_id = payload.gift_list_id
    # 2. TRIGGER DYNAMIC UPDATE: Manually update the folder's timestamp
    folder = db.query(UserGiftList).filter(UserGiftList.id == payload.gift_list_id).first()
    if folder:
        folder.updated_at = datetime.utcnow()
    db.commit()
    return APIResponse(status="success", message="Gift added to your list")

# get available all the items except those items that are already in the folder, to show in the "Add to list" modal 
@router.get("/gift-planner/folders/{folder_id}/available-items", response_model=APIResponse[List[HomeItemCard]])
async def get_available_items_for_folder(folder_id: int, api_request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetches items that can be added to a specific folder (i.e., not already in it)"""
    # Get item IDs already in the folder
    existing_item_ids = db.query(SavedItem.item_id).filter(SavedItem.gift_list_id == folder_id, SavedItem.user_id == current_user.id).all()
    existing_item_ids = [id for (id,) in existing_item_ids]  # Unpack from tuples

    # Fetch approved gift items not already in the folder
    items = db.query(PlatformItem).filter(
        PlatformItem.item_type == "gift",
        PlatformItem.status == "approved",
        ~PlatformItem.id.in_(existing_item_ids)  # Exclude items already in the folder
    ).all()

    result = []
    for item in items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        age_range = "0-20 years"
        if item.tags and isinstance(item.tags, list):
            age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
            if age_tags:
                age_range = age_tags[0]

        display_date = item.date or item.created_at
        result.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_name=item.category.name if item.category else "General",
            location=item.location or "N/A",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=age_range,
            date_label=display_date.strftime("%d %B %Y") if display_date else None,
            is_recommended=True,
            is_saved=False
        ))

    return APIResponse(status="success", message="Available items fetched", data=result)

"""saved items / bookmarks"""

# SAVED ITEMS TAB ENGINE 
@router.get("/saved/items", response_model=APIResponse[SavedItemsResponse])
async def get_my_saved_items(
    item_type: str = "activity",        # activity, event, or gift
    gift_list_id: Optional[int] = None, # Filter by folder (e.g., Birthday)
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Powers the 'Saved' screen tabs.
    - If type=gift: also returns the 'Browse from list' occasion pills.
    - Calculates distance for every saved item relative to user's current location.
    """
    
    # 1. Base Query: Join SavedItem with PlatformItem
    query = db.query(PlatformItem).join(
        SavedItem, SavedItem.item_id == PlatformItem.id
    ).filter(
        SavedItem.user_id == current_user.id,
        PlatformItem.item_type == item_type
    )

    # 2. Filter by specific Gift Folder (Image 1 "Browse from list")
    if item_type == "gift" and gift_list_id:
        query = query.filter(SavedItem.gift_list_id == gift_list_id)

    total_count = query.count()
    
    # 3. Paginate
    raw_items = query.order_by(SavedItem.created_at.desc()).offset((page-1)*limit).limit(limit).all()

    # 4. Process into UI Cards with Distance
    processed_cards = []
    for item in raw_items:
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
        processed_cards.append(HomeItemCard(
            id=item.id,
            item_type=item.item_type,
            name=item.name,
            image_url=item.image_url,
            category_name=item.category.name if item.category else "Health",
            price=item.price or 0.0,
            distance_km=dist,
            age_range="0-20 years", # Extracted from tags
            date_label=item.date.strftime("%d %b, %Y") if item.date else None,
            is_recommended=True,
            is_saved=True # Since it's from the saved table, this is always true
        ))

    # 5. For 'Gift' tab, fetch the occasion pills (folders)
    gift_folders = None
    if item_type == "gift":
        lists = db.query(UserGiftList).filter(UserGiftList.user_id == current_user.id).all()
        gift_folders = [GiftListResponse(id=l.id, name=l.name, items_count=len(l.saved_items)) for l in lists]

    data = SavedItemsResponse(
        total_count=total_count,
        page=page,
        items=processed_cards,
        gift_folders=gift_folders
    )

    return APIResponse(status="success", message="Saved items fetched", data=data)

# 1. MAIN PROFILE DASHBOARD 
@router.get("/profile/me", response_model=APIResponse[FullProfileResponse])
async def get_my_profile_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetches the user profile with calculated metrics and contributor status"""
    
    # Calculate real stats from DB
    rev_count = db.query(Review).filter(Review.user_id == current_user.id).count()
    act_count = db.query(PlatformItem).filter(PlatformItem.creator_id == current_user.id, PlatformItem.item_type == "activity").count()
    gift_count = db.query(PlatformItem).filter(PlatformItem.creator_id == current_user.id, PlatformItem.item_type == "gift").count()
    
    # Contributor Logic (Example algorithm)
    top_pct = "Top 9%"
    level = "Local Contributor"
    if rev_count > 50: level = "Expert Contributor"

    metrics = UserProfileMetrics(
        reviews_count=rev_count,
        activities_count=act_count,
        invited_family_count=12, # Mocked for MVP
        gifts_shared_count=gift_count,
        contributor_level=level,
        top_percentage=top_pct,
        progress_pct=0.75
    )

    data = FullProfileResponse(
        full_name=current_user.full_name,
        location_name=current_user.location_name or "Unknown",
        profile_image_url=current_user.profile_image_url,
        metrics=metrics
    )
    return APIResponse(status="success", message="Profile loaded", data=data)

# 2. EDIT PROFILE 
@router.put("/profile/update", response_model=APIResponse[None])
async def update_basic_profile(
    full_name: str = Form(...),
    location_name: str = Form(...),
    email: Optional[str] = Form(None), 
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    # 1. Update Email ONLY if provided and different from current
    if email and email != current_user.email:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already in use by another account.")
        current_user.email = email

    # 2. Handle Profile Picture Upload
    if photo and photo.filename:
        UPLOAD_DIR = "uploads/profiles"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        file_extension = photo.filename.split(".")[-1]
        file_name = f"user_{current_user.id}_{datetime.utcnow().timestamp()}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
            
        current_user.profile_image_url = f"/{file_path}".replace("\\", "/")

    # 3. Update Text Fields
    current_user.full_name = full_name
    current_user.location_name = location_name
    
    db.commit()
    
    return APIResponse(status="success", message="Profile updated successfully")

# GET CHILD INFORMATION 
@router.get("/profile/children", response_model=APIResponse[MyChildrenProfileResponse])
async def get_my_children_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fetches the user's location, expecting status, and existing children 
    to populate the "Child Information" edit screen and slider cards.
    """
    # Check if user is expecting
    expecting_child = db.query(Child).filter(
        Child.parent_id == current_user.id, 
        Child.is_expecting == True
    ).first()
    
    is_expecting = expecting_child is not None
    expected_date = expecting_child.expected_due_date.strftime("%d/%m/%Y") if is_expecting and expecting_child.expected_due_date else None

    # Fetch born kids
    kids = db.query(Child).filter(
        Child.parent_id == current_user.id, 
        Child.is_expecting == False
    ).all()
    
    kids_list = [
        ChildDetailInfo(
            id=k.id,
            name=k.name,
            dob=k.dob.strftime("%d/%m/%Y") if k.dob else None, # Formatted for the UI placeholder
            gender=k.gender
        ) for k in kids
    ]

    response_data = MyChildrenProfileResponse(
        location_name=current_user.location_name,
        is_expecting=is_expecting,
        expected_due_date=expected_date,
        kids=kids_list
    )
    
    return APIResponse(status="success", message="Child information loaded", data=response_data)


# UPDATE CHILD INFORMATION 
@router.put("/profile/children", response_model=APIResponse[None])
async def update_my_children_profile(
    payload: UpdateChildrenProfileRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Updates the Location and completely refreshes the Child records.
    """
    # 1. Update Location if provided
    if payload.location_name:
        current_user.location_name = payload.location_name

    # 2. Clear old child records to ensure a clean sync with the new form state
    db.query(Child).filter(Child.parent_id == current_user.id).delete()
    
    # 3. Save Expecting Info
    if payload.is_expecting:
        db.add(Child(
            parent_id=current_user.id,
            is_expecting=True,
            expected_due_date=payload.expected_due_date
        ))
    
    # 4. Save Kids Info (from the horizontal slider/list)
    else:
        for kid in payload.children:
            db.add(Child(
                parent_id=current_user.id,
                is_expecting=False,
                name=kid.name,
                dob=kid.dob,
                gender=kid.gender
            ))

    db.commit()
    return APIResponse(status="success", message="Child information updated successfully!")

@router.get("/profile/reviews", response_model=APIResponse[List[UserReviewItem]])
async def get_my_reviews_list(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Matches 'My Review' (Image 7)"""
    reviews = db.query(Review).filter(Review.user_id == current_user.id).order_by(Review.created_at.desc()).all()
    
    data = [UserReviewItem(
        id=r.id,
        place_name=r.item.name,
        date=r.created_at.strftime("%d %B %Y"),
        comment=r.comment,
        recommendation_label=r.recommendation_level
    ) for r in reviews]
    
    return APIResponse(status="success", message="Reviews fetched", data=data)

# 3. CONTACT SUPPORT & SUGGESTIONS 
@router.post("/profile/support", response_model=APIResponse[None])
async def submit_support_ticket(
    payload: SupportRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    # 1. Save to Database
    msg = SupportMessage(
        user_id=current_user.id,
        email=payload.email,
        location=payload.location,
        problem_details=payload.problem_details
    )
    db.add(msg)
    db.commit()

    # 2. Alert the Support Team via Email
    background_tasks.add_task(send_support_alert_to_admin, payload.email, payload.problem_details)

    return APIResponse(status="success", message="Your query has been submitted. We will contact you soon.")

@router.get("/profile/suggestions", response_model=APIResponse[dict])
async def get_my_suggestions(api_request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Matches 'Your Suggestions' / 'Suggested' (Image 5)"""
    
    # User suggestions are PlatformItems created by the user
    items = db.query(PlatformItem).filter(PlatformItem.creator_id == current_user.id).all()
    
    data = []
    for i in items:
        # Safe description slicing
        desc = ""
        if i.description:
            desc = i.description[:60] + "..." if len(i.description) > 60 else i.description
            
        data.append({
            "id": i.id,
            "name": i.name,
            "description": desc,
            "location": i.location,
            "image_url": get_full_url(api_request, i.image_url) if i.image_url else None,
            "status": i.status.capitalize() if i.status else "Pending", # Approved, Pending, Rejected
            "category": i.category.name if i.category else "General"    # Dynamic category name
        })
    
    return APIResponse(status="success", message="Suggestions fetched", data={"items": data})

# @router.get("/legal/privacy-policy")
# async def get_privacy_policy():
#     """Returns static text"""
#     return {"status": "success", "content": "FamilySide takes your privacy seriously..."}

@router.get("/legal/privacy-policy", response_model=APIResponse[dict])
async def get_dynamic_privacy_policy(db: Session = Depends(get_db)):
    """Returns the latest Privacy Policy content to the mobile app"""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == "privacy_policy").first()
    
    content = doc.content if doc else "Privacy Policy is being updated. Please check back soon."
    
    return APIResponse(
        status="success", 
        message="Privacy Policy loaded", 
        data={"content": content}
    )