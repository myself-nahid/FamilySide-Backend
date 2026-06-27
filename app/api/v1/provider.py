from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, extract

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.core_data import AnalyticsLog, Category, PlatformItem, Notification, Review, SubCategory
from app.schemas.auth_schema import APIResponse
from app.schemas.provider_schema import AnalyticsDataPoint, ContributorStats, ManagedEventItem, ProviderAnalyticsResponse, ProviderDropdownItem, ProviderEventsResponse, ProviderHomeHeader, ProviderItemCard, ProviderHomeResponse, ProviderItemDetailResponse, ProviderProfileResponse
from app.core.utils import calculate_distance_km, get_full_url
from app.schemas.provider_schema import AIFlyerExtractionResponse
from app.models.core_data import Notification
from app.schemas.family_schema import NotificationListResponse, NotificationGroup, NotificationItem
from datetime import timedelta
from fastapi import Form, File, UploadFile
from app.core.config import settings
from datetime import datetime, date
from typing import List, Optional
from openai import AsyncOpenAI
import base64
import random
import shutil
import json
import os

openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

router = APIRouter(prefix="/provider", tags=["Provider App - Home"])

@router.get("/home/header", response_model=APIResponse[ProviderHomeHeader])
async def get_provider_header(
    api_request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Matches UI Header: Welcome back [Name], Location, and Notifications"""
    if current_user.user_type != "provider":
        raise HTTPException(status_code=403, detail="Not authorized as a provider")

    unread = db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).count()

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
        status="success", message="Header loaded",
        data=ProviderHomeHeader(
            name=current_user.full_name,
            profile_image_url=full_image_url,
            location=current_user.location_name or "Dhaka, Bangladesh",
            unread_notifications=unread
        )
    )

@router.get("/home/feed", response_model=APIResponse[ProviderHomeResponse])
async def get_provider_home_feed(
    api_request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Fetches 'Upcoming Events' and 'Top Services' for this specific Provider"""
    
    # 1. Fetch upcoming events owned by this provider
    raw_events = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == "event",
        # Allow owner to see pending and approved items
        PlatformItem.status.in_(["approved", "pending"]) 
    ).order_by(PlatformItem.date.asc()).limit(3).all()

    # 2. Fetch top services (Activities) owned by this provider
    # Note: In a real app, 'top' would be based on views/bookings. Here we use newest.
    raw_services = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == "activity",
        PlatformItem.status.in_(["approved", "pending"])
    ).order_by(desc(PlatformItem.created_at)).limit(3).all()

    def format_item(item):
        return ProviderItemCard(
            id=item.id,
            name=item.name,
            image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
            category_label=item.category.name if item.category else "Birthday",
            item_type=item.item_type,
            price=item.price or 0.0,
            distance_km=0.05, # Distance from their own business is usually static/near
            age_range="Age: 0-20 years",
            date_label=item.date.strftime("%d %B, %Y") if item.date else "25 June, 2026"
        )

    return APIResponse(
        status="success", message="Provider feed loaded",
        data=ProviderHomeResponse(
            upcoming_events=[format_item(i) for i in raw_events],
            top_services=[format_item(i) for i in raw_services]
        )
    )

"""Manage Flow Endpoints (Add/Edit/Delete) for Provider's Own Items - Activities & Events"""
# 1. LIST OWNED ITEMS
@router.get("/manage/items", response_model=APIResponse[dict])
async def get_my_managed_items(
    api_request: Request,
    item_type: str = "activity", # activity, event, gift
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns a paginated list of items owned by the logged-in provider."""
    query = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == item_type
    )
    
    total_count = query.count()
    items = query.order_by(PlatformItem.created_at.desc()).offset((page-1)*limit).limit(limit).all()
    
    formatted_items = []
    for i in items:
        formatted_items.append(ProviderItemCard(
            id=i.id,
            name=i.name,
            image_url=get_full_url(api_request, i.image_url) if i.image_url else None,
            category_label=i.category.name if i.category else "General",
            item_type=i.item_type,
            price=i.price or 0.0,
            distance_km=0.0, # Provider's own items don't need distance logic
            age_range="Age: 0-20 years", # Extracted from tags
            date_label=i.date.strftime("%d %B, %Y") if i.date else None
        ))
        
    return APIResponse(
        status="success", 
        message=f"Total {total_count} {item_type}s found", 
        data={"total": total_count, "items": formatted_items}
    )

# 1.5 GET SPECIFIC ITEM FOR EDITING (Pre-fill Form)
@router.get("/manage/items/{item_id}", response_model=APIResponse[ProviderItemDetailResponse])
async def get_provider_item_for_edit(
    api_request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Fetches the raw data of a single item owned by the provider 
    so the frontend can pre-fill the "Edit" form.
    """
    item = db.query(PlatformItem).filter(
        PlatformItem.id == item_id,
        PlatformItem.creator_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or you don't own it")

    # Safely handle JSONB lists
    sub_cats = item.sub_categories if isinstance(item.sub_categories, list) else []
    tags_list = item.tags if isinstance(item.tags, list) else []

    data = ProviderItemDetailResponse(
        id=item.id,
        item_type=item.item_type,
        name=item.name,
        location=item.location,
        category_id=item.category_id,
        price=item.price or 0.0,
        description=item.description,
        website=item.website,
        whatsapp=item.whatsapp,
        email=item.email,
        instagram=item.instagram,
        opening_days=item.opening_days,
        opening_hours=item.opening_hours,
        # Format date and time so the frontend input fields can read them easily
        date=item.date.strftime("%Y-%m-%d") if item.date else None,
        time=item.start_time.strftime("%I:%M %p") if item.start_time else None,
        sub_categories=sub_cats,
        tags=tags_list,
        image_url=get_full_url(api_request, item.image_url),
        status=item.status
    )
    
    return APIResponse(status="success", message="Item data fetched", data=data)


@router.get("/items/{item_id}/view", response_model=APIResponse[ProviderItemDetailResponse])
async def view_item_details(
    api_request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Public-ish view for a single activity/event used by both Family and Provider apps."""
    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    sub_cats = item.sub_categories if isinstance(item.sub_categories, list) else []
    tags_list = item.tags if isinstance(item.tags, list) else []

    data = ProviderItemDetailResponse(
        id=item.id,
        item_type=item.item_type,
        name=item.name,
        location=item.location,
        category_id=item.category_id,
        price=item.price or 0.0,
        description=item.description,
        website=item.website,
        whatsapp=item.whatsapp,
        email=item.email,
        instagram=item.instagram,
        opening_days=item.opening_days,
        opening_hours=item.opening_hours,
        date=item.date.strftime("%Y-%m-%d") if item.date else None,
        time=item.start_time.strftime("%I:%M %p") if item.start_time else None,
        sub_categories=sub_cats,
        tags=tags_list,
        image_url=get_full_url(api_request, item.image_url) if item.image_url else None,
        status=item.status or "pending"
    )

    return APIResponse(status="success", message="Item details fetched", data=data)

# 2. UPDATE ITEM
@router.put("/manage/items/{item_id}", response_model=APIResponse[None])
async def update_provider_item(
    item_id: int,
    name: str = Form(...),            
    price: float = Form(...),         
    description: str = Form(...),     # Added description (required)
    location: Optional[str] = Form(None),
    
    # Optional fields for all types
    date: Optional[str] = Form(None),       # Added Date
    time: Optional[str] = Form(None),       # Added Time
    opening_days: Optional[str] = Form(None),
    opening_hours: Optional[str] = Form(None),
    
    sub_categories: str = Form("[]"), 
    tags: str = Form("[]"),           
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch item and check ownership
    item = db.query(PlatformItem).filter(
        PlatformItem.id == item_id, 
        PlatformItem.creator_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or unauthorized")

    # 2. Handle New Photo Upload (if provided)
    if photo and photo.filename:
        UPLOAD_DIR = f"uploads/{item.item_type}s"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_extension = photo.filename.split(".")[-1]
        file_path = os.path.join(UPLOAD_DIR, f"edit_{item_id}_{datetime.utcnow().timestamp()}.{file_extension}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        item.image_url = f"/{file_path}".replace("\\", "/")

    # 3. Update Text and Numeric Fields
    item.name = name
    item.price = price
    item.description = description
    if location: item.location = location
    if opening_days: item.opening_days = opening_days
    if opening_hours: item.opening_hours = opening_hours
    
    # Parse Date and Time if provided
    if date:
        try: item.date = datetime.strptime(date, "%Y-%m-%d").date()
        except: pass
    if time:
        try: 
            if "AM" in time.upper() or "PM" in time.upper():
                item.start_time = datetime.strptime(time, "%I:%M %p").time()
            else:
                item.start_time = datetime.strptime(time, "%H:%M").time()
        except: pass

    # 4. Parse and Update JSONB Fields (Chips)
    try: item.sub_categories = json.loads(sub_categories)
    except: item.sub_categories = [sub_categories]
        
    try: item.tags = json.loads(tags)
    except: item.tags = [tags]

    db.commit()
    
    return APIResponse(status="success", message=f"{item.item_type.capitalize()} updated successfully")

# 3. DELETE ITEM
@router.delete("/manage/items/{item_id}", response_model=APIResponse[None])
async def delete_provider_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Permanently removes an item after the user confirms in the UI modal."""
    item = db.query(PlatformItem).filter(
        PlatformItem.id == item_id, 
        PlatformItem.creator_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    db.delete(item)
    db.commit()
    
    return APIResponse(status="success", message="Item deleted successfully")

"""create and edit endpoints for provider items (activities/events) - these will be used in the 'Manage' section of the provider app"""
# Helper to notify Admin
def notify_admin(db: Session, item: PlatformItem, provider_name: str):
    new_notif = Notification(
        title=f"New {item.item_type.capitalize()} Added",
        subtitle=f"{provider_name} submitted '{item.name}' for approval",
        item_type=item.item_type,
        item_id=item.id,
        is_read=False
    )
    db.add(new_notif)
    db.commit()

# 1. CREATE ACTIVITY
@router.post("/create/activity", response_model=APIResponse[None])
async def provider_create_activity(
    name: str = Form(...),
    location: str = Form(...),
    lat: Optional[float] = Form(None), 
    lng: Optional[float] = Form(None),
    category_id: int = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None), # Matches "What's App Number"
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None), # Matches "Instagram Link"
    opening_days: Optional[str] = Form(None),
    opening_hours: Optional[str] = Form(None),
    sub_categories: str = Form("[]"), 
    tags: str = Form("[]"),           
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Handle Image Upload
    image_url = None
    if photo:
        os.makedirs("uploads/activities", exist_ok=True)
        path = f"uploads/activities/prov_{current_user.id}_{photo.filename}"
        with open(path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        image_url = path.replace("\\", "/")

    # 2. Map all fields to the Model
    new_item = PlatformItem(
        item_type="activity",
        name=name,
        location=location,
        lat=lat, 
        lng=lng,
        category_id=category_id,
        price=price,
        description=description,
        
        # New mapping
        website=website,
        whatsapp=whatsapp,
        email=email,
        instagram=instagram,
        opening_days=opening_days,
        opening_hours=opening_hours,
        
        sub_categories=json.loads(sub_categories),
        tags=json.loads(tags),
        image_url=image_url,
        creator_id=current_user.id,
        status="pending" 
    )
    
    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    # Trigger Admin Notification
    notify_admin(db, new_item, current_user.full_name)

    return APIResponse(status="success", message="Activity submitted successfully!")

# DROPDOWN HELPERS (For Create/Edit Forms)
@router.get("/categories/active", response_model=APIResponse[List[ProviderDropdownItem]])
async def get_active_categories_for_dropdown(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Called when the "Add Activity/Event" screen loads.
    Populates the 'Category' dropdown.
    """
    categories = db.query(Category).filter(Category.is_active == True).all()
    
    data = [ProviderDropdownItem(id=c.id, name=c.name) for c in categories]
    return APIResponse(status="success", message="Categories loaded", data=data)


@router.get("/categories/{category_id}/sub-categories", response_model=APIResponse[List[ProviderDropdownItem]])
async def get_active_sub_categories_for_dropdown(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Called IMMEDIATELY after the user selects a Category from the dropdown.
    Populates the 'Sub-category' chips below it.
    """
    sub_categories = db.query(SubCategory).filter(
        SubCategory.category_id == category_id,
        SubCategory.is_active == True
    ).all()
    
    data = [ProviderDropdownItem(id=s.id, name=s.name) for s in sub_categories]
    return APIResponse(status="success", message="Sub-categories loaded", data=data)

# 2. CREATE EVENT
@router.post("/create/event", response_model=APIResponse[None])
async def provider_create_event(
    name: str = Form(...),
    location: str = Form(...),          # Matches the top search bar
    lat: Optional[float] = Form(None),
    lng: Optional[float] = Form(None),
    category_id: int = Form(...),
    price: float = Form(...),           # Matches "Enter amount*"
    date: str = Form(...),              # Expected: "dd/mm/yyyy"
    time: str = Form(...),              # Expected: "hh:mm"
    description: str = Form(...),
    tags: str = Form("[]"),             # JSON string from multi-select
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Handle Photo Upload
    image_url = None
    if photo:
        os.makedirs("uploads/events", exist_ok=True)
        path = f"uploads/events/prov_{current_user.id}_{photo.filename}"
        with open(path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        image_url = f"/{path}"

    # 2. Parse Date (dd/mm/yyyy) and Time (hh:mm)
    try:
        parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use dd/mm/yyyy")

    try:
        # Supports both 24h (14:00) and 12h (02:00 PM) formats
        if "AM" in time.upper() or "PM" in time.upper():
            parsed_time = datetime.strptime(time, "%I:%M %p").time()
        else:
            parsed_time = datetime.strptime(time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use hh:mm or hh:mm AM/PM")

    # 3. Create Item
    new_event = PlatformItem(
        item_type="event",
        name=name,
        location=location,
        lat=lat,
        lng=lng,
        category_id=category_id,
        price=price,
        date=parsed_date,
        start_time=parsed_time,
        description=description,
        tags=json.loads(tags),
        image_url=image_url,
        creator_id=current_user.id,
        status="pending"
    )
    
    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    # 4. Trigger Admin Notification
    notify_admin(db, new_event, current_user.full_name)

    return APIResponse(status="success", message="Event submitted for approval!")

# AI FLYER EXTRACTION ENGINE
@router.post("/ai/parse-flyer", response_model=APIResponse[AIFlyerExtractionResponse])
async def ai_parse_flyer(
    flyer_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reads an uploaded promotional flyer using OpenAI Vision.
    Extracts text, parses event details, and suggests taxonomy tags.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")

    try:
        # 1. Read and encode the image to Base64
        image_bytes = await flyer_image.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # OpenAI only accepts specific formats. If Postman sends a weird type, we fix it.
        allowed_mimes = ["image/jpeg", "image/png", "image/webp", "image/gif"]
        mime_type = flyer_image.content_type
        
        if mime_type not in allowed_mimes:
            # Guess from file extension
            ext = flyer_image.filename.split(".")[-1].lower() if flyer_image.filename else "jpg"
            if ext == "png": mime_type = "image/png"
            elif ext == "webp": mime_type = "image/webp"
            elif ext == "gif": mime_type = "image/gif"
            else: mime_type = "image/jpeg" 

        # 2. Construct the strict JSON prompt for OpenAI
        prompt = """
        You are an AI assistant for a family and kids app. Extract the event/activity details from this flyer.
        Return ONLY a raw JSON object with the following keys. Do not include markdown formatting.
        - "name": Event or activity title.
        - "description": Summary of the event.
        - "date": Event date in DD/MM/YYYY format. If none, return null.
        - "start_time": Start time in HH:MM AM/PM format. If none, return null.
        - "location": Address or venue name.
        - "price": Numeric cost. If it says 'Free', return 0.0. Remove currency symbols.
        - "suggested_tags": Array of 2 to 4 relevant tags (e.g., ["Music", "Indoor", "Toddler", "Education", "Sports"]).
        """

        # 3. Call OpenAI gpt-4o (Vision capable)
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"}, 
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.2 
        )

        # 4. Parse the AI Response
        ai_raw_text = response.choices[0].message.content.strip()
        print(f"\n--- RAW AI RESPONSE ---\n{ai_raw_text}\n-----------------------\n")
        
        # Clean up markdown if OpenAI still wraps it
        if ai_raw_text.startswith("```"):
            lines = ai_raw_text.split('\n')
            if lines[0].startswith("```"): lines = lines[1:]
            if lines[-1].startswith("```"): lines = lines[:-1]
            ai_raw_text = '\n'.join(lines).strip()

        extracted_data = json.loads(ai_raw_text)

        # 5. Format to our Schema
        data = AIFlyerExtractionResponse(
            name=extracted_data.get("name"),
            description=extracted_data.get("description"),
            date=extracted_data.get("date"),
            start_time=extracted_data.get("start_time"),
            location=extracted_data.get("location"),
            price=float(extracted_data.get("price") or 0.0),
            suggested_tags=extracted_data.get("suggested_tags", [])
        )

        return APIResponse(status="success", message="Flyer parsed successfully", data=data)

    except json.JSONDecodeError:
        print(f"JSON Parsing Failed! AI Output was: {ai_raw_text}")
        raise HTTPException(status_code=500, detail="AI failed to return valid data. Please enter details manually.")
    except Exception as e:
        print(f"AI Parse Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process the flyer image.")

# 3. CREATE GIFT
@router.post("/create/gift", response_model=APIResponse[None])
async def provider_create_gift(
    name: str = Form(..., alias="gift_name"), # UI Label: Gift Name
    category_id: int = Form(...),            # UI Label: Category
    price: float = Form(...),                 # UI Label: Enter amount*
    description: str = Form(...),             # UI Label: Description
    tags: str = Form("[]"),                   # UI Label: Tag (multi-select)
    photo: Optional[UploadFile] = File(None), # UI Label: Add Photos
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Handles the 'Add New Gift' form.
    Items created here are saved with item_type='gift' and status='pending'.
    """
    # 1. Handle File Upload
    image_url = None
    if photo:
        os.makedirs("uploads/gifts", exist_ok=True)
        path = f"uploads/gifts/prov_{current_user.id}_{photo.filename}"
        with open(path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        image_url = f"/{path}"

    # 2. Parse Tags JSON
    try:
        parsed_tags = json.loads(tags)
    except:
        parsed_tags = [tags] if tags else []

    # 3. Create the Gift Item
    new_gift = PlatformItem(
        item_type="gift",
        name=name,
        category_id=category_id,
        price=price,
        description=description,
        tags=parsed_tags,
        image_url=image_url,
        creator_id=current_user.id,
        status="pending" # Sent to admin for approval
    )
    
    db.add(new_gift)
    db.commit()
    db.refresh(new_gift)

    # 4. Notify Admin
    notify_admin(db, new_gift, current_user.full_name)

    return APIResponse(status="success", message="Gift submitted for admin approval!")

"""Analytics Endpoints for Provider Dashboard - This will power the line chart and personalized suggestions in the provider app's analytics section"""
# 1. ANALYTICS DATA
@router.get("/analytics", response_model=APIResponse[ProviderAnalyticsResponse])
async def get_provider_analytics(
    category: str = "Profile Views", 
    year: int = 2025,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Calculates monthly performance data for the provider's dashboard.
    Matches Image 1: Category tabs, Year filter, and Line Chart.
    """
    if current_user.user_type != "provider":
        raise HTTPException(status_code=403, detail="Access denied")

    # 1. Map UI Categories to Action Types
    action_map = {
        "Profile Views": "profile_view",
        "User engagement": "item_view",
        "Total Activities": "item_view" # In a real app, this might count unique items
    }
    target_action = action_map.get(category, "profile_view")

    # 2. Generate Chart Data (Months Jan to Dec)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    chart_points = []
    
    for i, month_name in enumerate(months, start=1):
        # Count actions for this specific month and year
        count = db.query(AnalyticsLog).filter(
            AnalyticsLog.provider_id == current_user.id,
            AnalyticsLog.action_type == target_action,
            extract('year', AnalyticsLog.created_at) == year,
            extract('month', AnalyticsLog.created_at) == i
        ).count()
        
        # NOTE: To match your UI's negative values, this logic would compare 
        # this month vs last month to get a % growth. 
        # For this MVP, we return the count.
        chart_points.append(AnalyticsDataPoint(label=month_name, value=float(count)))

    # 3. Personalized Suggestions (Image 1 - Pink Card)
    # This can be powered by the OpenAI API logic from your project proposal
    suggestion = (
        "Users in your area are searching for 'Outdoor Play' 20% more this month. "
        "Consider adding more weekend slots to your activities to increase engagement."
    )

    return APIResponse(
        status="success", 
        message="Analytics loaded",
        data=ProviderAnalyticsResponse(
            category=category,
            year=year,
            chart_data=chart_points,
            suggestion_text=suggestion
        )
    )

"""profile management"""
# 1. CONTRIBUTOR DASHBOARD
@router.get("/profile/dashboard", response_model=APIResponse[ProviderProfileResponse])
async def get_contributor_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Calculate counts
    reviews = db.query(Review).filter(Review.user_id == current_user.id).count()
    activities = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id, 
        PlatformItem.item_type == "activity"
    ).count()
    gifts = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id, 
        PlatformItem.item_type == "gift"
    ).count()

    stats = ContributorStats(
        reviews_count=reviews,
        activities_count=activities,
        invited_family_count=12, # Logic for referrals
        gifts_shared_count=gifts,
        contributor_level="Local Contributor",
        progress_percentage=0.85
    )

    return APIResponse(
        status="success", message="Dashboard loaded",
        data=ProviderProfileResponse(
            name=current_user.full_name,
            location=current_user.location_name or "Dhaka, Bangladesh",
            image_url=current_user.profile_image_url,
            stats=stats
        )
    )

# 2. MANAGE EVENTS - UPCOMING VS COMPLETED
@router.get("/manage/events/status", response_model=APIResponse[ProviderEventsResponse])
async def get_provider_events_by_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Groups provider events into Upcoming and Completed tabs"""
    now = date.today()
    
    events = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == "event"
    ).all()

    upcoming = []
    completed = []

    for e in events:
        item = ManagedEventItem(
            id=e.id, name=e.name, item_type="Event",
            location=e.location or "Dhaka, Bangladesh",
            date=e.date.strftime("%d %B %Y") if e.date else "N/A",
            time=e.start_time.strftime("%I:%M %p") if e.start_time else "N/A",
            image_url=e.image_url
        )
        
        # Logic: If date is in the past, it's completed
        if e.date and e.date < now:
            completed.append(item)
        else:
            upcoming.append(item)

    return APIResponse(
        status="success", message="Events categorized",
        data=ProviderEventsResponse(upcoming=upcoming, completed=completed)
    )

# 3. MY SUGGESTIONS / SUBMISSIONS 
@router.get("/profile/my-submissions", response_model=APIResponse[dict])
async def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Matches 'Your Suggestions' (Image 7) showing Admin Approval status"""
    items = db.query(PlatformItem).filter(PlatformItem.creator_id == current_user.id).all()
    
    data = [{
        "id": i.id,
        "name": i.name,
        "description": i.description[:50] + "..." if i.description else "",
        "location": i.location or "Dhaka, Bangladesh",
        "status": i.status, # 'approved' (Green in UI), 'pending' (Orange in UI)
        "category": "Health"
    } for i in items]
    
    return APIResponse(status="success", message="Submissions fetched", data={"items": data})

# 4. MY REVIEWS
@router.get("/profile/my-reviews", response_model=APIResponse[list])
async def get_my_reviews(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    reviews = db.query(Review).filter(Review.user_id == current_user.id).all()
    
    data = [{
        "id": r.id,
        "place_name": r.item.name if r.item else "Unknown",
        "date": r.created_at.strftime("%d %B %Y"),
        "comment": r.comment,
        "recommendation": r.recommendation_level # "Recommended"
    } for r in reviews]
    
    return APIResponse(status="success", message="Reviews fetched", data=data)


# provider profile update
@router.put("/profile/update", response_model=APIResponse[None])
async def update_provider_profile(
    api_request: Request,
    name: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if name:
        current_user.full_name = name
    if location:
        current_user.location_name = location

    # Handle profile image upload
    if profile_image and profile_image.filename:
        os.makedirs("uploads/profile_images", exist_ok=True)
        file_extension = profile_image.filename.split(".")[-1]
        file_path = f"uploads/profile_images/user_{current_user.id}_{datetime.utcnow().timestamp()}.{file_extension}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(profile_image.file, buffer)
        current_user.profile_image_url = f"/{file_path}".replace("\\", "/")

    db.commit()
    
    return APIResponse(status="success", message="Profile updated successfully")

# NOTIFICATIONS
# Helper to format time (e.g. "5min ago", "3 days ago")
def get_time_ago(dt: datetime):
    now = datetime.utcnow()
    diff = now - dt
    if diff.days == 0:
        if diff.seconds < 3600: return f"{diff.seconds // 60}min ago"
        return f"{diff.seconds // 3600}h ago"
    if diff.days < 7: return f"{diff.days} days ago"
    return dt.strftime("%d %b")

@router.get("/notifications", response_model=APIResponse[NotificationListResponse])
async def get_provider_notifications(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Fetches and groups notifications for the Provider Dashboard"""
    if current_user.user_type != "provider":
        raise HTTPException(status_code=403, detail="Not authorized as a provider")
        
    notifications = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).all()

    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).count()

    # Initialize buckets for UI
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
async def mark_all_provider_notifications_read(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Marks all notifications as read when the user opens the notification screen"""
    if current_user.user_type != "provider":
        raise HTTPException(status_code=403, detail="Not authorized as a provider")
        
    db.query(Notification).filter(
        Notification.user_id == current_user.id, 
        Notification.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    return APIResponse(status="success", message="All notifications marked as read")