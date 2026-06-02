from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.core_data import PlatformItem, Category, SavedItem, SubCategory
from app.schemas.auth_schema import APIResponse
from app.schemas.family_schema import HomeHeaderResponse, HomeItemCard, HomeFeedResponse, CategoryTab, SearchFilterParams, SubCategoryListResponse
from app.core.utils import calculate_distance_km

router = APIRouter(prefix="/family", tags=["Family App - Home"])

@router.get("/home/header", response_model=APIResponse[HomeHeaderResponse])
async def get_home_header(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Matches the top section of Image 8: Name, Location, Notification Bell"""
    
    # Note: For MVP, we mock unread notifications to 3 (as seen in UI) 
    # until the user notification mapping is fully implemented.
    unread_count = 3 
    
    first_name = current_user.full_name.split(" ")[0] if current_user.full_name else "Guest"
    
    return APIResponse(
        status="success", message="Header loaded",
        data=HomeHeaderResponse(
            first_name=first_name,
            location_name=current_user.location_name or "Set your location",
            unread_notifications=unread_count
        )
    )

@router.get("/home/feed", response_model=APIResponse[HomeFeedResponse])
async def get_home_feed(
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
            # Calculate exact distance from user to the item
            dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
            
            # Extract Age range safely from JSON tags
            age_range = "0-20 years" # Fallback default
            if item.tags and isinstance(item.tags, list):
                age_tags = [t for t in item.tags if "year" in t.lower() or "age" in t.lower()]
                if age_tags: age_range = age_tags[0]

            # Determine Date Label (Events use specific date, Activities don't)
            date_label = None
            if is_event and item.date:
                date_label = item.date.strftime("%d %b")

            card = HomeItemCard(
                id=item.id,
                item_type=item.item_type,
                name=item.name,
                image_url=item.image_url,
                category_name=item.category.name if item.category else "Uncategorized",
                price=item.price or 0.0,
                distance_km=dist,
                age_range=age_range,
                date_label=date_label,
                is_recommended=True,
                is_saved=(item.id in saved_item_ids)
            )
            
            processed_list.append({
                "card": card, 
                "raw_distance": dist if dist is not None else 9999.0, # Push items without location to the back
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
            image_url=None, # Use a default placeholder in frontend if null
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
        # A. Calculate Distance
        dist = calculate_distance_km(current_user.lat, current_user.lng, item.lat, item.lng)
        
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
            image_url=item.image_url,
            category_name=item.category.name if item.category else "General",
            price=item.price or 0.0,
            distance_km=dist,
            age_range=params.child_age or "0-20 years",
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