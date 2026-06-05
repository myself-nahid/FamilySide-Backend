from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.core_data import PlatformItem, Notification
from app.schemas.auth_schema import APIResponse
from app.schemas.provider_schema import ProviderHomeHeader, ProviderItemCard, ProviderHomeResponse
from app.core.utils import calculate_distance_km

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