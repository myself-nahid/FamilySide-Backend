from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.core_data import PlatformItem, Notification
from app.schemas.auth_schema import APIResponse
from app.schemas.provider_schema import ProviderHomeHeader, ProviderItemCard, ProviderHomeResponse
from app.core.utils import calculate_distance_km
from fastapi import Form, File, UploadFile
from typing import Optional
import os
import shutil
import json


router = APIRouter(prefix="/provider", tags=["Provider App - Home"])

@router.get("/home/header", response_model=APIResponse[ProviderHomeHeader])
async def get_provider_header(
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

    return APIResponse(
        status="success", message="Header loaded",
        data=ProviderHomeHeader(
            name=current_user.full_name,
            location=current_user.location_name or "Dhaka, Bangladesh",
            unread_notifications=unread
        )
    )

@router.get("/home/feed", response_model=APIResponse[ProviderHomeResponse])
async def get_provider_home_feed(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Fetches 'Upcoming Events' and 'Top Services' for this specific Provider"""
    
    # 1. Fetch upcoming events owned by this provider
    raw_events = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == "event",
        PlatformItem.status == "approved"
    ).order_by(PlatformItem.date.asc()).limit(3).all()

    # 2. Fetch top services (Activities) owned by this provider
    # Note: In a real app, 'top' would be based on views/bookings. Here we use newest.
    raw_services = db.query(PlatformItem).filter(
        PlatformItem.creator_id == current_user.id,
        PlatformItem.item_type == "activity",
        PlatformItem.status == "approved"
    ).order_by(desc(PlatformItem.created_at)).limit(3).all()

    def format_item(item):
        return ProviderItemCard(
            id=item.id,
            name=item.name,
            image_url=item.image_url,
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
            image_url=i.image_url,
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

# 2. UPDATE ITEM
@router.put("/manage/items/{item_id}", response_model=APIResponse[None])
async def update_provider_item(
    item_id: int,
    name: str = Form(...),
    location: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    tags: Optional[str] = Form(None),           # JSON string
    sub_categories: Optional[str] = Form(None), # JSON string
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch item and verify ownership
    item = db.query(PlatformItem).filter(
        PlatformItem.id == item_id, 
        PlatformItem.creator_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or you don't own it")

    # 2. Update Image if new photo provided
    if photo:
        UPLOAD_DIR = f"uploads/{item.item_type}s"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, f"update_{item_id}_{photo.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        item.image_url = f"/{file_path}"

    # 3. Update Text Fields
    item.name = name
    item.location = location
    item.price = price
    item.description = description
    
    if tags:
        try: item.tags = json.loads(tags)
        except: pass
    if sub_categories:
        try: item.sub_categories = json.loads(sub_categories)
        except: pass

    db.commit()
    return APIResponse(status="success", message="Item updated successfully")

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