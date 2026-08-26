from alembic.environment import Optional
from alembic.util import status
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.api.deps import get_db, get_current_admin
from app.core.utils import get_full_url
from app.models.user import User, Child, Interest
from app.models.core_data import LegalDocument, PlatformItem, Category, SupportMessage, Tag, SubCategory, Notification, GiftCardDesign
from app.schemas.auth_schema import APIResponse, ChangePasswordRequest
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
import pandas as pd
import numpy as np
from io import BytesIO
import os
import shutil
import json
import base64
from openai import AsyncOpenAI, AuthenticationError
from app.schemas.admin_schema import (
    DashboardOverviewResponse, LegalDocumentResponse, TrendMetric, StatusDistribution,
    FlaggedItemListItem, PendingApprovalListItem, UpcomingEventListItem,
    ChartDataResponse, ChartDataPoint
)
from app.schemas.admin_schema import (
    DashboardStatsResponse, UserActionRequest, 
    ItemStatusUpdateRequest, CreateItemRequest, AdminProfileUpdateRequest, UserDetailResponse, ChildResponse, NotificationItem, ItemReviewDetailResponse, ActivityListItem, ActivityDetailResponse, CreateActivityRequest, EventListItem, EventDetailResponse, GiftListItem, GiftDetailResponse, GiftCardDesignItem, GiftCardDesignDetailResponse, AdminProfileResponse, AIFlyerExtractionResponse, GiftAIFlyerExtractionResponse
)

from app.schemas.admin_schema import BulkDeleteRequest
from app.schemas.admin_schema import TaxonomyRequest, SubCategoryRequest, TaxonomyResponseItem, LegalDocumentRequest, InterestRequest, InterestResponseItem
from app.core.security import get_password_hash, verify_password
from typing import List
import googlemaps
from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


def parse_list_field(raw):
    """Accept either JSON arrays or comma-separated strings."""
    if raw is None:
        return []

    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]

    if isinstance(raw, tuple):
        return [str(v).strip() for v in raw if str(v).strip()]

    value = str(raw).strip()
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except Exception:
        parsed = value

    if isinstance(parsed, list):
        return [str(v).strip() for v in parsed if str(v).strip()]

    if isinstance(parsed, tuple):
        return [str(v).strip() for v in parsed if str(v).strip()]

    return [part.strip() for part in str(parsed).split(",") if part.strip()]


openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Helper function to calculate Trend Metrics (This Week vs Last Week)
def calculate_trend(db: Session, query_base, date_field) -> TrendMetric:
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # Count for this week (last 7 days)
    this_week_count = query_base.filter(date_field >= one_week_ago).count()
    # Count for previous week (7 to 14 days ago)
    last_week_count = query_base.filter(and_(date_field >= two_weeks_ago, date_field < one_week_ago)).count()

    total_count = query_base.count()

    if last_week_count == 0:
        percentage_change = 100.0 if this_week_count > 0 else 0.0
    else:
        percentage_change = round(((this_week_count - last_week_count) / last_week_count) * 100, 1)

    return TrendMetric(
        count=total_count,
        percentage_change=abs(percentage_change),
        is_increase=percentage_change >= 0
    )


def _build_ai_flyer_prompt(item_type: str) -> str:
    if item_type == "activity":
        return f"""
    You are an AI assistant for a family and kids app. Your job is to extract data from this image/flyer.
    Read ALL the text on the image. Even if the data is messy, try your best to extract it.
    This flyer represents an {item_type}.
    Return ONLY a raw JSON object with the exact keys below.
    
    - "name": The title of the {item_type}. (If no title is obvious, use the largest text).
    - "description": A summary of what this is, or just extract the main body text you see.
    - "opening_days": The day(s) the activity is available, e.g. "Mon-Fri" or "Weekends". If none, return null.
    - "opening_hours": The hours when the activity is open, e.g. "10:00 AM to 08:00 PM". If none, return null.
    - "location": The address, venue name, or city mentioned. If none, return null.
    - "price": The numeric cost. If it says 'Free', return 0.0. Remove currency symbols like $. If no price is mentioned, return null.
    - "suggested_tags": Array of 2 to 4 relevant tags (e.g., ["Music", "Indoor", "Toddler", "Education", "Sports"]).
    
    If you cannot find an exact match for a field, try to infer it from the context before returning null.
    """
    if item_type == "gift":
        return f"""
    You are an AI assistant for a family and kids app. Your job is to extract data from this image/flyer.
    Read ALL the text on the image. Even if the data is messy, try your best to extract it.
    This flyer represents a gift.
    Return ONLY a raw JSON object with the exact keys below.
    
    - "name": The title of the gift. (If no title is obvious, use the largest text).
    - "description": A summary of the gift or the offer details.
    - "price": The numeric amount or value. If it says 'Free', return 0.0. Remove currency symbols like $. If no amount is mentioned, return null.
    - "suggested_tags": Array of 2 to 4 relevant tags (e.g., ["Toddler", "Indoor", "Free", "Paid"]).
    
    Do not include a "location" field in the response.
    If you cannot find an exact match for a field, try to infer it from the context before returning null.
    """
    return f"""
    You are an AI assistant for a family and kids app. Your job is to extract data from this image/flyer.
    Read ALL the text on the image. Even if the data is messy, try your best to extract it.
    This flyer represents a {item_type}.
    Return ONLY a raw JSON object with the exact keys below.
    
    - "name": The title of the {item_type}. (If no title is obvious, use the largest text).
    - "description": A summary of what this is, or just extract the main body text you see.
    - "date": Event date in DD/MM/YYYY format. If no date is found, return null.
    - "start_time": Start time in HH:MM AM/PM format. If no time is found, return null.
    - "location": The address, venue name, or city mentioned. If none, return null.
    - "price": The numeric cost. If it says 'Free', return 0.0. Remove currency symbols like $. If no price is mentioned, return null.
    - "suggested_tags": Array of 2 to 4 relevant tags (e.g., ["Music", "Indoor", "Toddler", "Education", "Sports"]).
    
    If you cannot find an exact match for a field, try to infer it from the context before returning null.
    """


async def _parse_flyer_image(flyer_image: UploadFile, item_type: str) -> AIFlyerExtractionResponse:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")

    image_bytes = flyer_image.file.read() if hasattr(flyer_image.file, 'read') else flyer_image.read()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    mime_type = flyer_image.content_type or "image/jpeg"

    if mime_type not in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
        ext = flyer_image.filename.split(".")[-1].lower() if flyer_image.filename else "jpg"
        if ext == "png":
            mime_type = "image/png"
        elif ext == "webp":
            mime_type = "image/webp"
        elif ext == "gif":
            mime_type = "image/gif"
        else:
            mime_type = "image/jpeg"

    prompt = _build_ai_flyer_prompt(item_type)

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]}
            ],
            max_tokens=500,
            temperature=0.2
        )
    except Exception as exc:
        message = str(exc)
        if AuthenticationError is not None and isinstance(exc, AuthenticationError):
            raise HTTPException(status_code=401, detail="Invalid OpenAI API key configured.")
        if "invalid_api_key" in message or "Incorrect API key" in message:
            raise HTTPException(status_code=401, detail="Invalid OpenAI API key configured.")
        raise HTTPException(status_code=500, detail="Failed to call OpenAI API.")

    ai_raw_text = response.choices[0].message.content.strip()
    if ai_raw_text.startswith("```"):
        lines = ai_raw_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        ai_raw_text = "\n".join(lines).strip()

    extracted_data = json.loads(ai_raw_text)

    return AIFlyerExtractionResponse(
        name=extracted_data.get("name"),
        description=extracted_data.get("description"),
        date=extracted_data.get("date"),
        start_time=extracted_data.get("start_time"),
        opening_days=extracted_data.get("opening_days"),
        opening_hours=extracted_data.get("opening_hours"),
        location=extracted_data.get("location"),
        price=float(extracted_data.get("price") or 0.0),
        suggested_tags=extracted_data.get("suggested_tags", [])
    )


# Helper to resolve a user-friendly creator label
def resolve_creator_label(user) -> str:
    """
    Return one of: 'Admin', 'Provider', 'Family', or a best-effort label
    based on the User record attached to an item.
    """
    if not user:
        return "Admin"
    if getattr(user, "is_admin", False):
        return "Admin"
    user_type = getattr(user, "user_type", None)
    if user_type:
        if user_type.lower() == "provider":
            return "Provider"
        if user_type.lower() == "family":
            return "Family"
        return user_type.capitalize()
    return "User"

"""
1. DASHBOARD OVERVIEW (Top Cards + Trends + Donut Chart + Bottom Lists)
"""

# 1.1 Dashboard Overview (Top Cards + Donut Chart + Bottom Lists)
@router.get("/dashboard/overview", response_model=APIResponse[DashboardOverviewResponse])
async def get_dashboard_overview(api_request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """
    Returns the complete dashboard overview data including top stats, 
    donut chart metrics, and recent bottom tables.
    """
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)

    # 1. Top Static Cards
    pending_approvals = db.query(PlatformItem).filter(PlatformItem.status == "pending").count()
    flagged_reviews = db.query(PlatformItem).filter(PlatformItem.status == "flagged").count()
    new_providers_this_week = db.query(User).filter(and_(User.user_type == "provider", User.join_date >= one_week_ago)).count()

    # 2. Trend Metrics Cards (Week over Week)
    total_users_query = db.query(User).filter(User.user_type == "family")
    total_users_trend = calculate_trend(db, total_users_query, User.join_date)

    new_users_query = db.query(User).filter(User.user_type == "family")
    new_users_trend = calculate_trend(db, new_users_query, User.join_date)

    activities_query = db.query(PlatformItem).filter(PlatformItem.item_type == "activity")
    activities_trend = calculate_trend(db, activities_query, PlatformItem.created_at)

    events_query = db.query(PlatformItem).filter(PlatformItem.item_type == "event")
    events_trend = calculate_trend(db, events_query, PlatformItem.created_at)

    gifts_query = db.query(PlatformItem).filter(PlatformItem.item_type == "gift")
    gifts_trend = calculate_trend(db, gifts_query, PlatformItem.created_at)

    # 3. Items by Status (Donut Chart Percentages)
    total_items = db.query(PlatformItem).count() or 1 # Avoid division by zero
    approved_count = db.query(PlatformItem).filter(PlatformItem.status == "approved").count()
    pending_count = db.query(PlatformItem).filter(PlatformItem.status == "pending").count()
    rejected_count = db.query(PlatformItem).filter(PlatformItem.status == "rejected").count()
    flagged_count = db.query(PlatformItem).filter(PlatformItem.status == "flagged").count()

    status_dist = StatusDistribution(
        approved_pct=round((approved_count / total_items) * 100, 1),
        pending_pct=round((pending_count / total_items) * 100, 1),
        rejected_pct=round((rejected_count / total_items) * 100, 1),
        flagged_pct=round((flagged_count / total_items) * 100, 1)
    )

    # 4. Bottom Lists
    # A. Recent Flagged Items
    raw_flagged = db.query(PlatformItem).filter(PlatformItem.status == "flagged").order_by(PlatformItem.created_at.desc()).limit(4).all()
    recent_flagged_list = [
        FlaggedItemListItem(id=item.id, name=item.name, image_url=get_full_url(api_request, item.image_url) if item.image_url else None, item_type=item.item_type.capitalize(), time_ago="1 hr ago")
        for item in raw_flagged
    ]

    # B. To-Do Today (Pending Approvals)
    raw_pending = db.query(PlatformItem).filter(PlatformItem.status == "pending").order_by(PlatformItem.created_at.desc()).limit(4).all()
    pending_todo_list = [
        PendingApprovalListItem(id=item.id, name=item.name, item_type=item.item_type.capitalize())
        for item in raw_pending
    ]

    # C. Upcoming Events
    raw_events = db.query(PlatformItem).filter(
        and_(PlatformItem.item_type == "event", PlatformItem.date >= now.date())
    ).order_by(PlatformItem.date.asc()).limit(4).all()
    
    upcoming_events_list = [
        UpcomingEventListItem(
            id=event.id, 
            name=event.name,
            image_url=get_full_url(api_request, event.image_url) if event.image_url else None,
            date=event.date.strftime("%d %b %Y") if event.date else "N/A",
            time=event.start_time.strftime("%I:%M %p") if event.start_time else "N/A"
        )
        for event in raw_events
    ]

    # Combine into unified response
    response_data = DashboardOverviewResponse(
        pending_approvals=pending_approvals,
        flagged_reviews=flagged_reviews,
        new_providers=new_providers_this_week,
        total_users=total_users_trend,
        new_users_this_week=new_users_trend,
        activities=activities_trend,
        events=events_trend,
        gifts=gifts_trend,
        status_distribution=status_dist,
        recent_flagged=recent_flagged_list,
        pending_todo=pending_todo_list,
        upcoming_events=upcoming_events_list
    )

    return APIResponse(status="success", message="Dashboard overview successfully loaded", data=response_data)


# 1.2 INTERACTIVE LINE CHART FILTERING API (Activity Overview) (Trends)
@router.get("/dashboard/chart", response_model=APIResponse[ChartDataResponse])
async def get_dashboard_chart(
    tab: str = "activity",        # activity, events, users, reviews
    timeframe: str = "year",      # year, month, week
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns data points dynamically calculated for the "Activity Overview" line chart.
    """
    points = []
    now = datetime.utcnow()

    # Determine query entity and target date field based on tab selected
    if tab in ["activity", "events", "reviews"]:
        entity = PlatformItem
        date_col = PlatformItem.created_at
        filter_type = "activity" if tab == "activity" else ("event" if tab == "events" else None)
    else:
        entity = User
        date_col = User.join_date
        filter_type = None

    # Filter query
    query = db.query(entity)
    if filter_type:
        query = query.filter(PlatformItem.item_type == filter_type)

    # Grouping logic depending on timeframe
    if timeframe == "year":
        # Group by Month (1 to 12) for the current year
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for i, month_label in enumerate(months, start=1):
            count = query.filter(
                and_(
                    func.extract('year', date_col) == now.year,
                    func.extract('month', date_col) == i
                )
            ).count()
            points.append(ChartDataPoint(label=month_label, value=count))

    elif timeframe == "month":
        # Group by Weeks of the current month
        for week_num in range(1, 5):
            start_day = (week_num - 1) * 7 + 1
            end_day = week_num * 7
            count = query.filter(
                and_(
                    func.extract('year', date_col) == now.year,
                    func.extract('month', date_col) == now.month,
                    func.extract('day', date_col) >= start_day,
                    func.extract('day', date_col) <= end_day
                )
            ).count()
            points.append(ChartDataPoint(label=f"Week {week_num}", value=count))

    elif timeframe == "week":
        # Group by Days of the current week (Mon-Sun)
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        start_of_week = now - timedelta(days=now.weekday())
        for i, day_label in enumerate(days):
            target_date = start_of_week + timedelta(days=i)
            count = query.filter(
                func.date(date_col) == target_date.date()
            ).count()
            points.append(ChartDataPoint(label=day_label, value=count))

    return APIResponse(
        status="success", 
        message="Chart data loaded", 
        data=ChartDataResponse(tab=tab, timeframe=timeframe, points=points)
    )


# 1.3 VIEW ALL FLAGGED ITEMS (Matches "Recent flagged items -> View all")
@router.get("/items/flagged", response_model=APIResponse[dict])
async def get_all_flagged_items(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all flagged items on the platform.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "flagged")
    
    # Enable searching by item name if search query is provided
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    
    # Paginate using offset and limit
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "item_type": item.item_type.capitalize(),
                "created_at": item.created_at.strftime("%Y-%m-%d") if item.created_at else None,
                "location": item.location
            } for item in items
        ]
    }
    
    return APIResponse(status="success", message="Flagged items fetched", data=pagination_data)


# 1.4 VIEW ALL PENDING APPROVALS (Matches "To do today -> View all")
@router.get("/items/pending/all", response_model=APIResponse[dict])
async def get_all_pending_approvals(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all pending approvals on the platform.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "pending")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "item_type": item.item_type.capitalize(),
                "created_at": item.created_at.strftime("%Y-%m-%d") if item.created_at else None,
                "location": item.location
            } for item in items
        ]
    }
    
    return APIResponse(status="success", message="Pending approvals fetched", data=pagination_data)


# 1.5 VIEW ALL UPCOMING EVENTS (Matches "Upcoming Events -> View all")
@router.get("/items/upcoming/all", response_model=APIResponse[dict])
async def get_all_upcoming_events_paginated(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all approved upcoming events,
    sorted by date ascending (closest events first).
    """
    now = datetime.utcnow()
    query = db.query(PlatformItem).filter(
        and_(
            PlatformItem.item_type == "event",
            PlatformItem.status == "approved",
            PlatformItem.date >= now.date()
        )
    )
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.date.asc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": event.id,
                "name": event.name,
                "date": event.date.strftime("%d %b %Y") if event.date else "N/A",
                "time": event.start_time.strftime("%I:%M %p") if event.start_time else "N/A",
                "location": event.location,
                "price": event.price
            } for event in items
        ]
    }
    
    return APIResponse(status="success", message="Upcoming events fetched", data=pagination_data)

"""
2. USER MANAGEMENT 
"""
# 2.1 LIST USERS - PAGINATED & FILTERED
@router.get("/users", response_model=APIResponse[dict])
async def get_users_paginated(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,         # Search by Name or Email
    user_type: Optional[str] = "all",     # all, family, provider
    status: Optional[str] = None,         # Active, Suspended, Blocked
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated list of all system users. 
    Supports full search queries and strict administrative filtering.
    """
    query = db.query(User).filter(User.id != admin.id)
    
    # Apply Filters
    if user_type and user_type != "all":
        query = query.filter(User.user_type == user_type)
        
    if status:
        query = query.filter(User.status == status)
        
    if search:
        query = query.filter(
            (User.full_name.ilike(f"%{search}%")) | 
            (User.email.ilike(f"%{search}%"))
        )
        
    total_count = query.count()
    offset = (page - 1) * limit
    
    # Order by newest users first
    users = query.order_by(User.join_date.desc()).offset(offset).limit(limit).all()
    
    # Map users to matching UI table columns
    user_list = [
        {
            "id": u.id,
            "name": u.full_name,
            "email": u.email,
            "user_type": u.user_type.capitalize() if u.user_type else "User",
            "location": u.location_name or "New work, UAS",
            "join_date": u.join_date.strftime("%d/%m/%Y") if u.join_date else "N/A",
            "subscription": u.subscription_plan or "Free",  
            "status": u.status or "Active"                  
        }
        for u in users
    ]
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "users": user_list
    }
    
    return APIResponse(status="success", message="Users fetched", data=pagination_data)

# get all users (except admin) details without pagination
@router.get("/users/all", response_model=APIResponse[List[UserDetailResponse]])
async def get_all_users_details(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # Fetch all users except the current admin
    users = db.query(User).filter(User.id != admin.id).all()
    
    response_data = []
    
    for user in users:
        # 1. Calculate the missing metrics for this specific user
        activities_created = db.query(PlatformItem).filter(
            PlatformItem.creator_id == user.id, 
            PlatformItem.item_type == "activity"
        ).count()
        
        # You can query real tables for these if you want, using mock counts for now
        mock_reviews = 0       
        mock_saved = 0         
        contributor_level = "Top 9%" 
        
        # 2. Map the children for this specific user
        children_data = [
            ChildResponse(
                id=child.id,
                name=child.name or "Unnamed",
                dob=child.dob.strftime("%d/%m/%Y") if child.dob else "N/A",
                gender=child.gender or "Male"
            )
            for child in user.children
        ]
        
        # 3. Create the complete object with NO missing fields
        response_data.append(UserDetailResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role or "Parent",
            join_date=user.join_date.strftime("%d/%m/%Y") if user.join_date else "N/A",
            location_name=user.location_name or "New work, UAS",
            status=user.status or "Active",                      
            subscription_plan=user.subscription_plan or "Free",  
            reviews_count=mock_reviews,             
            activities_count=activities_created,    
            saved_items_count=mock_saved,           
            contributor_level=contributor_level,    
            children=children_data                  
        ))
        
    return APIResponse(
        status="success", 
        message="All user details fetched", 
        data=response_data
    )


# 2.2 DETAILED USER REVIEW MODAL
@router.get("/users/{user_id}", response_model=APIResponse[UserDetailResponse])
async def get_user_detail_review(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Fetches the deep profile of a user, including total platform metrics, 
    their contributor level, and list of registered children.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Query actual platform metrics
    activities_created = db.query(PlatformItem).filter(
        PlatformItem.creator_id == user_id, 
        PlatformItem.item_type == "activity"
    ).count()
    
    # Dynamic calculations for the review modal stats card
    mock_reviews = 32       # Replace with db.query(Review).filter(...).count()
    mock_saved = 12         # Replace with db.query(Bookmark).filter(...).count()
    contributor_level = "Top 9%" # Logical algorithm based on reviews
    
    # Map Children relation (Image 1)
    children_data = [
        ChildResponse(
            id=child.id,
            name=child.name or "Unnamed",
            dob=child.dob.strftime("%d/%m/%Y") if child.dob else "N/A",
            gender=child.gender or "Male"
        )
        for child in user.children
    ]
    
    response_data = UserDetailResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role or "Father",
        join_date=user.join_date.strftime("%d/%m/%Y") if user.join_date else "N/A",
        location_name=user.location_name or "New work, UAS",
        status=user.status or "Active",                      
        subscription_plan=user.subscription_plan or "Free",  
        reviews_count=mock_reviews,
        activities_count=activities_created,
        saved_items_count=mock_saved,
        contributor_level=contributor_level,
        children=children_data
    )
    
    return APIResponse(status="success", message="User review details fetched", data=response_data)


# 2.3 BLOCK/SUSPEND/ACTIVATE ACTION 
@router.patch("/users/{user_id}/action", response_model=APIResponse[None])
async def update_user_status_action(
    user_id: int,
    payload: UserActionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Processes administrative account actions (Block, Suspend, Activate).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    action_type = payload.action.lower()
    
    if action_type == "block":
        user.status = "Blocked"
        user.is_active = False
    elif action_type == "suspend":
        user.status = "Suspended"
        user.is_active = False
    elif action_type == "activate":
        user.status = "Active"
        user.is_active = True
    else:
        raise HTTPException(status_code=400, detail="Invalid action type.")
        
    db.commit()
    return APIResponse(status="success", message=f"User account status has been updated to {user.status}")
    

"""
3. NOTIFICATIONS
This section covers all notification-related endpoints, including fetching paginated notifications, viewing detailed item modals, and approving/rejecting items directly from notifications.
"""

# 3.1 GET PAGINATED NOTIFICATIONS
@router.get("/notifications", response_model=APIResponse[dict])
async def get_notifications_paginated(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated list of all administrative notifications,
    ordered by the newest notifications first.
    """
    query = db.query(Notification)
    total_count = query.count()
    offset = (page - 1) * limit
    
    notifications = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
    
    # Format dates into friendly UI formats (e.g. "Tuesday 2:00 PM")
    formatted_list = []
    for n in notifications:
        formatted_list.append({
            "id": n.id,
            "title": n.title,
            "subtitle": n.subtitle,
            "item_type": n.item_type,
            "item_id": n.item_id,
            "is_read": n.is_read,
            "time_label": n.created_at.strftime("%A %I:%M %p") if n.created_at else "Today"
        })
        
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "notifications": formatted_list
    }
    
    return APIResponse(status="success", message="Notifications fetched", data=pagination_data)


# 3.2 VIEW DETAILED ITEM MODAL
@router.get("/notifications/{notification_id}/view", response_model=APIResponse[ItemReviewDetailResponse])
async def view_notification_item_detail(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Resolves a notification and returns the exact detailed structural layout 
    of the linked Item (Activity, Event, or Gift) to populate review modals.
    """
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Associated item no longer exists")
        
    # Mark notification as read
    notification.is_read = True
    db.commit()
    
    # Gather tags & categories safely
    tags = ["Indoor", "Ongoing", "Free"] # Default mock tags for UI display
    sub_categories = ["Doctors", "Nurseries", "Playgrounds"] # Mock sub-categories
    
    # Map the object dynamically based on what type of item it is
    detail = ItemReviewDetailResponse(
        id=item.id,
        item_type=item.item_type,
        name=item.name,
        creator_email=item.creator.email if item.creator else "abc@gmail.com",
        category=item.category.name if item.category else "Uncategorized",
        sub_categories=sub_categories,
        tags=tags,
        price=item.price,
        description=item.description,
        website=item.website,
        instagram_link=item.instagram,
        whatsapp_number=item.whatsapp,
        date=item.date.strftime("%d/%m/%Y") if item.date else None,
        time=item.start_time.strftime("%I:%M %p") if item.start_time else None
    )
    
    return APIResponse(status="success", message="Item details fetched successfully", data=detail)


# 3.3 APPROVE ITEM
@router.post("/notifications/{notification_id}/approve", response_model=APIResponse[None])
async def approve_notification_item(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    # Approve Item
    item.status = "approved"
    
    # Remove from notifications list as action is complete
    db.delete(notification)
    db.commit()
    
    return APIResponse(status="success", message=f"{item.item_type.capitalize()} has been approved and is now live!")


# 3.4 REJECT ITEM (Matches Images 5 & 9 Reject flow)
@router.post("/notifications/{notification_id}/reject", response_model=APIResponse[None])
async def reject_notification_item(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Rejects the item, changing its database status to 'rejected'
    and clearing it out of the active notifications table.
    """
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    # Reject Item
    item.status = "rejected"
    
    # Remove from notifications list as action is complete
    db.delete(notification)
    db.commit()
    
    return APIResponse(status="success", message=f"{item.item_type.capitalize()} has been rejected successfully.")


"""4. ACTIVITY MANAGEMENT
This section includes all endpoints related to managing activities, including listing activities with pagination and search, viewing detailed activity modals, creating new activities, and deleting activities. These endpoints are designed to support the full lifecycle of activity management from the admin dashboard."""

# 4.1 GET ALL ACTIVITIES (Paginated + Searchable + Filter by Creator Type)
@router.get("/activities", response_model=APIResponse[dict])
async def get_activities_paginated(
    api_request: Request,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    creator_type: Optional[str] = "all", # Filter by "Admin", "User", "Provider"
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    query = db.query(PlatformItem).filter(PlatformItem.item_type == "activity")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    # Join with User table to filter by creator type if needed
    if creator_type and creator_type != "all":
        if creator_type.lower() == "admin":
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.is_admin == True)
        else:
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    activities = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    activity_list = []
    for activity in activities:
        creator_label = resolve_creator_label(activity.creator)
            
        activity_list.append(ActivityListItem(
            id=activity.id,
            name=activity.name,
            image_url=get_full_url(api_request, activity.image_url) if activity.image_url else None,
            created_by=creator_label,
            category=activity.category.name if activity.category else "Uncategorized",
            location=activity.location or "N/A",
            fee=activity.price or 0.0
        ))
        
    return APIResponse(
        status="success", 
        message="Activities fetched", 
        data={"total": total_count, "page": page, "limit": limit, "items": activity_list}
    )

# 4.0 ADMIN AI FLYER PARSING FOR ACTIVITIES
@router.post("/ai/parse-flyer/activity", response_model=APIResponse[AIFlyerExtractionResponse])
async def admin_ai_parse_activity_flyer(
    flyer_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    data = await _parse_flyer_image(flyer_image, "activity")
    return APIResponse(status="success", message="Activity flyer parsed successfully", data=data)

# get all activities without pagination
@router.get("/activities/all", response_model=APIResponse[List[ActivityListItem]])
async def get_all_activities(
    api_request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a list of all activities without pagination, for quick access or dropdowns.
    """
    activities = db.query(PlatformItem).filter(PlatformItem.item_type == "activity").order_by(PlatformItem.created_at.desc()).all()
    
    activity_list = []
    for activity in activities:
        creator_label = resolve_creator_label(activity.creator)
            
        activity_list.append(ActivityListItem(
            id=activity.id,
            name=activity.name,
            image_url=get_full_url(api_request, activity.image_url) if activity.image_url else None,
            created_by=creator_label,
            category=activity.category.name if activity.category else "Uncategorized",
            location=activity.location or "N/A",
            fee=activity.price or 0.0
        ))
        
    return APIResponse(status="success", message="All activities fetched", data=activity_list)

# 4.2 VIEW ACTIVITY DETAILS 
@router.get("/activities/{activity_id}", response_model=APIResponse[ActivityDetailResponse])
async def get_activity_detail(
    api_request: Request,
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    creator_label = resolve_creator_label(activity.creator)

    # Mock tags for MVP display purposes
    # mock_tags = ["Education", "Indoor", "Paid"]

    parsed_sub_categories = activity.sub_categories if isinstance(activity.sub_categories, list) else []
    parsed_tags = activity.tags if isinstance(activity.tags, list) else []

    detail = ActivityDetailResponse(
        id=activity.id,
        name=activity.name,
        image_url=get_full_url(api_request, activity.image_url) if activity.image_url else None,
        description=activity.description,
        website=activity.website,
        location=activity.location,
        created_by=creator_label,
        status=activity.status.capitalize(),
        date_added=activity.created_at.strftime("%d %b %Y") if activity.created_at else "N/A",
        whatsapp=activity.whatsapp,
        email=activity.email,
        instagram=activity.instagram,
        category=activity.category.name if activity.category else "Uncategorized",
        category_id=activity.category_id,
        sub_categories=parsed_sub_categories,
        sub_category_ids=[s.get("id") for s in parsed_sub_categories if isinstance(s, dict) and s.get("id") is not None],
        tags=parsed_tags or ["Indoor", "Ongoing", "Free"],
        tag_ids=[t.get("id") for t in parsed_tags if isinstance(t, dict) and t.get("id") is not None],
        price=activity.price,
        opening_days=activity.opening_days,
        opening_hours=activity.opening_hours,
    )
    
    return APIResponse(status="success", message="Activity details fetched", data=detail)

# 4.3 CREATE ACTIVITY
@router.post("/activities", response_model=APIResponse[None])
async def create_activity(
    request: Request,
    # Core fields
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    
    # Optional text fields
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    opening_days: Optional[str] = Form(None),
    opening_hours: Optional[str] = Form(None),
    
    # Multi-select fields (Sent as JSON strings from frontend)
    sub_categories: Optional[str] = Form(None), # e.g., '["Doctors", "Nurseries"]'
    tags: Optional[str] = Form(None),           # e.g., '["Indoor", "Paid"]'
    
    # Image Upload
    photo: Optional[UploadFile] = File(None),
    
    # Dependencies
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # 1. Handle File Upload or Plain Text URL
    form = await request.form()
    upload_file = form.get("photo") or form.get("image_url")
    saved_image_path = None
    if upload_file is not None:
        if hasattr(upload_file, "filename") and upload_file.filename:
            UPLOAD_DIR = "uploads/activities"
            os.makedirs(UPLOAD_DIR, exist_ok=True)

            # Create a unique filename
            file_extension = upload_file.filename.split(".")[-1]
            file_name = f"activity_{datetime.utcnow().timestamp()}.{file_extension}"
            file_path = os.path.join(UPLOAD_DIR, file_name)

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_image_path = f"/{file_path}".replace("\\", "/")
        else:
            saved_image_path = str(upload_file).strip() or None

    # 2. Parse JSON strings back to Python lists
    parsed_sub_categories = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)

    # 3. Save to Database
    # Initialize Google Maps client (optional)
    gmaps = None
    if settings.GOOGLE_MAPS_API_KEY:
        try:
            gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
        except Exception:
            gmaps = None

    # Attempt to geocode the provided `location` if possible
    lat_val = None
    lng_val = None
    if location and gmaps:
        try:
            geocode_result = gmaps.geocode(location)
            if geocode_result:
                loc = geocode_result[0].get('geometry', {}).get('location')
                if loc:
                    lat_val = loc.get('lat')
                    lng_val = loc.get('lng')
        except Exception:
            # Fail silently — geocoding is best-effort
            lat_val = None
            lng_val = None

    new_activity = PlatformItem(
        item_type="activity",
        name=name,
        location=location,
        lat=lat_val,
        lng=lng_val,
        category_id=category_id,
        price=price,
        description=description,
        website=website,
        whatsapp=whatsapp,
        email=email,
        instagram=instagram,
        opening_days=opening_days,
        opening_hours=opening_hours,
        sub_categories=parsed_sub_categories, # Save as JSON
        tags=parsed_tags,                     # Save as JSON
        image_url=saved_image_path,           # Save the uploaded image URL
        creator_id=admin.id,
        status="approved" # Auto-approved by admin
    )
    
    db.add(new_activity)
    db.commit()
    try:
        db.refresh(new_activity)
    except Exception:
        pass
    # Refresh to ensure any DB defaults/triggers are loaded into the instance
    try:
        db.refresh(new_activity)
    except Exception:
        # If refresh fails (older SQLAlchemy dialects or SQLite quirks), ignore gracefully
        pass
    
    return APIResponse(status="success", message="Activity created successfully with photo!")

@router.put("/activities/{activity_id}", response_model=APIResponse[None])
async def update_activity(
    request: Request,
    activity_id: int,
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    opening_days: Optional[str] = Form(None),
    opening_hours: Optional[str] = Form(None),
    sub_categories: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    activity = db.query(PlatformItem).filter(PlatformItem.id == activity_id, PlatformItem.item_type == "activity").first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    form = await request.form()
    upload_file = form.get("photo") or form.get("image_url")
    saved_image_path = activity.image_url
    if upload_file is not None:
        if hasattr(upload_file, "filename") and upload_file.filename:
            UPLOAD_DIR = "uploads/activities"
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            file_extension = upload_file.filename.split(".")[-1]
            file_name = f"activity_{datetime.utcnow().timestamp()}.{file_extension}"
            file_path = os.path.join(UPLOAD_DIR, file_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_image_path = f"/{file_path}".replace("\\", "/")
        else:
            text_url = str(upload_file).strip()
            saved_image_path = text_url or activity.image_url

    parsed_sub_categories = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)

    gmaps = None
    if settings.GOOGLE_MAPS_API_KEY:
        try:
            gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
        except Exception:
            gmaps = None

    lat_val = activity.lat
    lng_val = activity.lng
    if location and gmaps:
        try:
            geocode_result = gmaps.geocode(location)
            if geocode_result:
                loc = geocode_result[0].get('geometry', {}).get('location')
                if loc:
                    lat_val = loc.get('lat')
                    lng_val = loc.get('lng')
        except Exception:
            pass

    activity.name = name
    activity.location = location
    activity.category_id = category_id
    activity.price = price
    activity.description = description
    activity.website = website
    activity.whatsapp = whatsapp
    activity.email = email
    activity.instagram = instagram
    activity.opening_days = opening_days
    activity.opening_hours = opening_hours
    activity.sub_categories = parsed_sub_categories
    activity.tags = parsed_tags
    activity.image_url = saved_image_path
    activity.lat = lat_val
    activity.lng = lng_val

    db.commit()
    return APIResponse(status="success", message="Activity updated successfully!")

# @router.post("/activities/bulk-upload", response_model=APIResponse[dict])
# async def bulk_upload_activities(
#     file: UploadFile = File(...),
#     db: Session = Depends(get_db),
#     admin: User = Depends(get_current_admin)
# ):
#     """
#     Production-grade Bulk Upload with Duplicate Handling and Row-level validation.
#     """
#     if not file.filename.endswith('.xlsx'):
#         raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

#     try:
#         contents = await file.read()
#         df = pd.read_excel(BytesIO(contents))
        
#         # Replace NaN with None for database compatibility
#         df = df.where(pd.notnull(df), None)

#         success_count = 0
#         update_count = 0
#         errors = []
        
#         # Default image path for activities
#         DEFAULT_IMAGE = "uploads/defaults/default_activity.png"

#         for index, row in df.iterrows():
#             # index + 2 because Excel starts at 1 and has a header row
#             row_num = index + 2 
            
#             try:
#                 # 1. VALIDATION: Check required fields
#                 if not row.get('name') or not row.get('location'):
#                     errors.append(f"Row {row_num}: Missing required Name or Location.")
#                     continue

#                 # 2. VALIDATION: Ensure Category exists
#                 cat_id = int(row['category_id']) if row.get('category_id') else None
#                 if not cat_id:
#                     errors.append(f"Row {row_num}: Missing category_id.")
#                     continue
                    
#                 category = db.query(Category).filter(Category.id == cat_id).first()
#                 if not category:
#                     errors.append(f"Row {row_num}: Category ID {cat_id} not found in database.")
#                     continue

#                 # 3. HELPER: Format comma-separated strings for JSONB
#                 def format_list(val):
#                     if not val: return []
#                     return [item.strip() for item in str(val).split(',')]

#                 # 4. DUPLICATE CHECK: Does this Name + Location already exist?
#                 existing_item = db.query(PlatformItem).filter(
#                     PlatformItem.name == str(row['name']).strip(),
#                     PlatformItem.location == str(row['location']).strip(),
#                     PlatformItem.item_type == "activity"
#                 ).first()

#                 # 5. IMAGE HANDLING
#                 raw_img = row.get('image_url')
#                 final_image_path = str(raw_img).strip().replace("\\", "/") if raw_img else DEFAULT_IMAGE

#                 if existing_item:
#                     # SCENARIO: UPDATE EXISTING (Duplicate Handling)
#                     existing_item.description = str(row.get('description', ''))
#                     existing_item.category_id = cat_id
#                     existing_item.price = float(row.get('price', 0.0))
#                     existing_item.website = row.get('website')
#                     existing_item.whatsapp = str(row.get('whatsapp')) if row.get('whatsapp') else None
#                     existing_item.email = row.get('email')
#                     existing_item.instagram = row.get('instagram')
#                     existing_item.opening_days = row.get('opening_days')
#                     existing_item.opening_hours = row.get('opening_hours')
#                     existing_item.sub_categories = format_list(row.get('sub_categories'))
#                     existing_item.tags = format_list(row.get('tags'))
#                     existing_item.image_url = final_image_path
#                     update_count += 1
#                 else:
#                     # SCENARIO: CREATE NEW
#                     new_activity = PlatformItem(
#                         item_type="activity",
#                         name=str(row['name']).strip(),
#                         description=str(row.get('description', '')),
#                         category_id=cat_id,
#                         location=str(row['location']).strip(),
#                         lat=float(row['lat']) if row.get('lat') else None,
#                         lng=float(row['lng']) if row.get('lng') else None,
#                         price=float(row.get('price', 0.0)),
#                         website=row.get('website'),
#                         whatsapp=str(row.get('whatsapp')) if row.get('whatsapp') else None,
#                         email=row.get('email'),
#                         instagram=row.get('instagram'),
#                         opening_days=row.get('opening_days'),
#                         opening_hours=row.get('opening_hours'),
#                         sub_categories=format_list(row.get('sub_categories')),
#                         tags=format_list(row.get('tags')),
#                         image_url=final_image_path,
#                         creator_id=admin.id,
#                         status="approved"
#                     )
#                     db.add(new_activity)
#                     success_count += 1

#             except Exception as e:
#                 errors.append(f"Row {row_num}: Data error - {str(e)}")

#         db.commit()

#         return APIResponse(
#             status="success", 
#             message=f"Processing complete: {success_count} added, {update_count} updated.",
#             data={
#                 "new_added": success_count,
#                 "updated": update_count,
#                 "failed": len(errors),
#                 "errors": errors 
#             }
#         )

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

@router.post("/activities/bulk-upload", response_model=APIResponse[dict])
async def bulk_upload_activities(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    # Initialize Google Maps Client
    gmaps = None
    if settings.GOOGLE_MAPS_API_KEY:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)

    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))

        # 1. Typo-proofing and Header Cleaning
        column_mapping = {'ing': 'lng', 'Name': 'name', 'Location': 'location'}
        df.rename(columns=column_mapping, inplace=True)

        # Robust NaN -> None normalization (pandas versions differ)
        df = df.replace({np.nan: None})

        # Prefetch valid category ids to validate rows before commit
        valid_cat_ids = {cid for (cid,) in db.query(Category.id).all()}

        success_count = 0
        update_count = 0
        errors = []
        DEFAULT_IMAGE = "uploads/defaults/default_activity.png"

        for index, row in df.iterrows():
            row_num = index + 2 
            try:
                # Basic Validation
                if not row.get('name') or not row.get('location'):
                    errors.append(f"Row {row_num}: Missing Name or Location.")
                    continue

                cat_id = int(row['category_id']) if row.get('category_id') is not None else None
                if cat_id is None:
                    errors.append(f"Row {row_num}: Missing category_id.")
                    continue
                if cat_id not in valid_cat_ids:
                    errors.append(f"Row {row_num}: Unknown category_id {cat_id}.")
                    continue

                lat_val = row.get('lat')
                lng_val = row.get('lng')
                address = str(row['location']).strip()

                # Duplicate Check — do this BEFORE any external geocoding calls
                existing_item = db.query(PlatformItem).filter(
                    PlatformItem.name == str(row['name']).strip(),
                    PlatformItem.location == address,
                    PlatformItem.item_type == "activity"
                ).first()

                # If coordinates are missing, fetch them from Google ONLY when we need them:
                # - creating a new item, or
                # - updating an existing item that has no stored coordinates and the file provides none
                need_geocode = False
                if gmaps and address:
                    if not existing_item and (not lat_val or not lng_val):
                        need_geocode = True
                    elif existing_item:
                        db_has_coords = existing_item.lat is not None and existing_item.lng is not None
                        file_has_coords = lat_val is not None and lng_val is not None
                        if (not db_has_coords) and (not file_has_coords):
                            need_geocode = True

                if need_geocode:
                    try:
                        geocode_result = gmaps.geocode(address)
                        if geocode_result:
                            loc = geocode_result[0]['geometry']['location']
                            lat_val = loc['lat']
                            lng_val = loc['lng']
                    except Exception as geo_err:
                        print(f"Geocoding failed for row {row_num}: {geo_err}")

                def format_list(val):
                    if not val: return []
                    return [item.strip() for item in str(val).split(',')]

                raw_img = row.get('image_url')
                final_image_path = str(raw_img).strip().replace("\\", "/") if raw_img else DEFAULT_IMAGE

                if existing_item:
                    # Update Existing — only overwrite fields if the column is present in the file
                    if 'lat' in df.columns and lat_val is not None:
                        existing_item.lat = float(lat_val)
                    if 'lng' in df.columns and lng_val is not None:
                        existing_item.lng = float(lng_val)
                    if 'description' in df.columns and row.get('description') is not None:
                        existing_item.description = str(row.get('description'))
                    if 'price' in df.columns and row.get('price') is not None:
                        existing_item.price = float(row.get('price'))
                    if 'image_url' in df.columns:
                        existing_item.image_url = final_image_path
                    # Contact and opening-hours: only overwrite when uploaded cell is non-empty
                    if 'website' in df.columns and row.get('website') not in (None, ''):
                        existing_item.website = row.get('website')
                    if 'whatsapp' in df.columns and row.get('whatsapp') not in (None, ''):
                        existing_item.whatsapp = str(row.get('whatsapp'))
                    if 'email' in df.columns and row.get('email') not in (None, ''):
                        existing_item.email = row.get('email')
                    if 'instagram' in df.columns and row.get('instagram') not in (None, ''):
                        existing_item.instagram = row.get('instagram')
                    if 'opening_days' in df.columns and row.get('opening_days') not in (None, ''):
                        existing_item.opening_days = row.get('opening_days')
                    if 'opening_hours' in df.columns and row.get('opening_hours') not in (None, ''):
                        existing_item.opening_hours = row.get('opening_hours')
                    # Update category/tags/sub_categories if provided in the file
                    if 'category_id' in df.columns:
                        existing_item.category_id = cat_id
                    if 'sub_categories' in df.columns:
                        existing_item.sub_categories = format_list(row.get('sub_categories'))
                    if 'tags' in df.columns:
                        existing_item.tags = format_list(row.get('tags'))
                    update_count += 1
                else:
                    # Create New
                    # Ensure numeric conversions handle None
                    lat_conv = float(lat_val) if lat_val is not None else None
                    lng_conv = float(lng_val) if lng_val is not None else None
                    price_conv = float(row.get('price')) if row.get('price') is not None else 0.0

                    new_activity = PlatformItem(
                        item_type="activity",
                        name=str(row['name']).strip(),
                        location=address,
                        lat=lat_conv,
                        lng=lng_conv,
                        category_id=cat_id,
                        price=price_conv,
                        description=str(row.get('description')) if row.get('description') is not None else None,
                        website=row.get('website') if 'website' in df.columns else None,
                        whatsapp=str(row.get('whatsapp')) if ('whatsapp' in df.columns and row.get('whatsapp') is not None) else None,
                        email=row.get('email') if 'email' in df.columns else None,
                        instagram=row.get('instagram') if 'instagram' in df.columns else None,
                        opening_days=row.get('opening_days') if 'opening_days' in df.columns else None,
                        opening_hours=row.get('opening_hours') if 'opening_hours' in df.columns else None,
                        sub_categories=format_list(row.get('sub_categories')),
                        tags=format_list(row.get('tags')),
                        image_url=final_image_path,
                        creator_id=admin.id,
                        status="approved"
                    )
                    db.add(new_activity)
                    success_count += 1

            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

        db.commit()
        return APIResponse(
            status="success", 
            message=f"Import complete: {success_count} added, {update_count} updated.",
            data={"new": success_count, "updated": update_count, "errors": errors}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File error: {str(e)}")

# 4.4 DELETE ACTIVITY 
@router.delete("/activities/{activity_id}", response_model=APIResponse[None])
async def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    activity = db.query(PlatformItem).filter(PlatformItem.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    db.delete(activity)
    db.commit()
    
    return APIResponse(status="success", message="Activity deleted successfully")

@router.post("/activities/bulk-delete", response_model=APIResponse[dict])
async def bulk_delete_activities(
    payload: BulkDeleteRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Delete multiple activities by ID. Returns count of deleted items and any errors."""
    ids = payload.ids or []
    if not ids:
        raise HTTPException(status_code=400, detail="No activity IDs provided for deletion")

    deleted_count = 0
    errors = []

    for item_id in ids:
        item = db.query(PlatformItem).filter(PlatformItem.id == item_id, PlatformItem.item_type == "activity").first()
        if not item:
            errors.append(f"Activity ID {item_id} not found")
            continue
        try:
            db.delete(item)
            deleted_count += 1
        except Exception as e:
            errors.append(f"Failed to delete {item_id}: {str(e)}")

    db.commit()

    return APIResponse(status="success", message=f"Deleted {deleted_count} activities", data={"deleted": deleted_count, "errors": errors})


# 4.5 BLOCK ACTIVITY 
@router.patch("/activities/{activity_id}/block", response_model=APIResponse[None])
async def block_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Blocks an activity, making it invisible to end-users 
    but keeping it in the admin records.
    """
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    if activity.status == "blocked":
        raise HTTPException(status_code=400, detail="Activity is already blocked")
        
    # Change status to blocked
    activity.status = "blocked"
    db.commit()
    
    return APIResponse(status="success", message=f"Activity '{activity.name}' has been blocked successfully.")

# 4.6 UNBLOCK ACTIVITY
@router.patch("/activities/{activity_id}/unblock", response_model=APIResponse[None])
async def unblock_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Restores a blocked activity back to approved status."""
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    activity.status = "approved"
    db.commit()
    
    return APIResponse(status="success", message=f"Activity '{activity.name}' has been restored.")


"""5. EVENT MANAGEMENT
This section includes all endpoints related to managing events, including listing events with pagination, search, and creator type filtering, viewing detailed event modals, creating new events with form-data and file upload, and deleting events. These endpoints are designed to support the full lifecycle of event management from the admin dashboard."""

# 5.1 GET ALL EVENTS (Paginated + Searchable + Filter by Creator Type)
@router.get("/events", response_model=APIResponse[dict])
async def get_events_paginated(
    api_request: Request,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    creator_type: Optional[str] = "all", # Filter by "Admin", "User", "Provider"
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    query = db.query(PlatformItem).filter(PlatformItem.item_type == "event")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    if creator_type and creator_type != "all":
        if creator_type.lower() == "admin":
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.is_admin == True)
        else:
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    events = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    event_list = []
    for event in events:
        creator_label = resolve_creator_label(event.creator)
            
        event_list.append(EventListItem(
            id=event.id,
            name=event.name,
            image_url=get_full_url(api_request, event.image_url) if event.image_url else None,
            created_by=creator_label,
            category=event.category.name if event.category else "Uncategorized",
            location=event.location or "N/A",
            fee=event.price or 0.0
        ))
        
    return APIResponse(
        status="success", 
        message="Events fetched", 
        data={"total": total_count, "page": page, "limit": limit, "items": event_list}
    )

# 5.0 ADMIN AI FLYER PARSING FOR EVENTS
@router.post("/ai/parse-flyer/event", response_model=APIResponse[AIFlyerExtractionResponse])
async def admin_ai_parse_event_flyer(
    flyer_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    data = await _parse_flyer_image(flyer_image, "event")
    return APIResponse(status="success", message="Event flyer parsed successfully", data=data)

# get all events without pagination
@router.get("/events/all", response_model=APIResponse[List[EventListItem]])
async def get_all_events(
    api_request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a list of all events without pagination.
    """
    events = db.query(PlatformItem).filter(PlatformItem.item_type == "event").order_by(PlatformItem.created_at.desc()).all()
    
    event_list = []
    for event in events:
        creator_label = resolve_creator_label(event.creator)
            
        event_list.append(EventListItem(
            id=event.id,
            name=event.name,
            image_url=get_full_url(api_request, event.image_url) if event.image_url else None,
            created_by=creator_label,
            category=event.category.name if event.category else "Uncategorized",
            location=event.location or "N/A",
            fee=event.price or 0.0
        ))
        
    return APIResponse(status="success", message="All events fetched", data=event_list)

# 5.2 VIEW EVENT DETAILS 
@router.get("/events/{event_id}", response_model=APIResponse[EventDetailResponse])
async def get_event_detail(
    api_request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    event = db.query(PlatformItem).filter(
        PlatformItem.id == event_id, 
        PlatformItem.item_type == "event"
    ).first()
    
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    creator_label = resolve_creator_label(event.creator)

    # Combine start and end time into one readable string
    time_str = "N/A"
    if event.start_time:
        time_str = event.start_time.strftime("%I:%M %p")
        if event.end_time:
            time_str += f" to {event.end_time.strftime('%I:%M %p')}"

    parsed_sub_categories = event.sub_categories if isinstance(event.sub_categories, list) else []
    parsed_tags = event.tags if isinstance(event.tags, list) else []

    detail = EventDetailResponse(
        id=event.id,
        name=event.name,
        image_url=get_full_url(api_request, event.image_url) if event.image_url else None,
        description=event.description,
        website=event.website,
        location=event.location,
        created_by=creator_label,
        status=event.status.capitalize(),
        date_added=event.created_at.strftime("%d %b %Y") if event.created_at else "N/A",
        whatsapp=event.whatsapp,
        category=event.category.name if event.category else "Uncategorized",
        category_id=event.category_id,
        sub_categories=parsed_sub_categories,
        sub_category_ids=[s.get("id") for s in parsed_sub_categories if isinstance(s, dict) and s.get("id") is not None],
        tags=parsed_tags,
        tag_ids=[t.get("id") for t in parsed_tags if isinstance(t, dict) and t.get("id") is not None],
        price=event.price,
        date=event.date.strftime("%d %b %Y") if event.date else "N/A",
        time=time_str,
    )
    
    return APIResponse(status="success", message="Event details fetched", data=detail)


# 5.3 CREATE EVENT 
@router.post("/events", response_model=APIResponse[None])
async def create_event(
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    
    # Dates and times
    date: Optional[str] = Form(None),         
    start_time: Optional[str] = Form(None),   
    end_time: Optional[str] = Form(None),     
    
    # JSON Arrays
    sub_categories: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    
    # --- FIXED IMAGE HANDLING ---
    photo: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # 1. Handle File Upload OR Text URL
    saved_image_path = None
    
    # Priority 1: A physical file was uploaded via the 'photo' key
    if photo and photo.filename:
        UPLOAD_DIR = "uploads/events"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        file_extension = photo.filename.split(".")[-1]
        file_name = f"event_{datetime.utcnow().timestamp()}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
            
        # Format the path with forward slashes for the database
        saved_image_path = f"/{file_path}".replace("\\", "/")
        
    # Priority 2: A text URL was provided via the 'image_url' key
    elif image_url and image_url.strip():
        saved_image_path = image_url.strip()


    # 2. Parse JSON fields (Sub-categories and Tags)
    parsed_sub = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)


    # 3. Parse Dates and Times safely
    parsed_date = None
    parsed_start = None
    parsed_end = None
    
    if date:
        try: parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
        except: 
            try: parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            except: pass
            
    if start_time:
        try: parsed_start = datetime.strptime(start_time, "%I:%M %p").time()
        except: 
            try: parsed_start = datetime.strptime(start_time, "%H:%M").time()
            except: pass
            
    if end_time:
        try: parsed_end = datetime.strptime(end_time, "%I:%M %p").time()
        except: 
            try: parsed_end = datetime.strptime(end_time, "%H:%M").time()
            except: pass

    # 4. Save to Database
    new_event = PlatformItem(
        item_type="event",
        name=name,
        location=location,
        category_id=category_id,
        price=price,
        description=description,
        website=website,
        whatsapp=whatsapp,
        email=email,
        instagram=instagram,
        date=parsed_date,
        start_time=parsed_start,
        end_time=parsed_end,
        sub_categories=parsed_sub,
        tags=parsed_tags,
        image_url=saved_image_path,  
        creator_id=admin.id,
        status="approved"
    )
    
    db.add(new_event)
    db.commit()
    
    return APIResponse(status="success", message="Event created successfully!")

@router.put("/events/{event_id}", response_model=APIResponse[None])
async def update_event(
    event_id: int,
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    date: Optional[str] = Form(None),
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
    sub_categories: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    event = db.query(PlatformItem).filter(PlatformItem.id == event_id, PlatformItem.item_type == "event").first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    saved_image_path = event.image_url
    if photo and photo.filename:
        UPLOAD_DIR = "uploads/events"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_extension = photo.filename.split(".")[-1]
        file_name = f"event_{datetime.utcnow().timestamp()}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        saved_image_path = f"/{file_path}".replace("\\", "/")
    elif image_url and image_url.strip():
        saved_image_path = image_url.strip()

    parsed_sub = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)

    parsed_date = None
    parsed_start = None
    parsed_end = None
    if date:
        try:
            parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
        except:
            try:
                parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            except:
                parsed_date = None
    if start_time:
        try:
            parsed_start = datetime.strptime(start_time, "%I:%M %p").time()
        except:
            try:
                parsed_start = datetime.strptime(start_time, "%H:%M").time()
            except:
                parsed_start = None
    if end_time:
        try:
            parsed_end = datetime.strptime(end_time, "%I:%M %p").time()
        except:
            try:
                parsed_end = datetime.strptime(end_time, "%H:%M").time()
            except:
                parsed_end = None

    event.name = name
    event.location = location
    event.category_id = category_id
    event.price = price
    event.description = description
    event.website = website
    event.whatsapp = whatsapp
    event.email = email
    event.instagram = instagram
    event.date = parsed_date
    event.start_time = parsed_start
    event.end_time = parsed_end
    event.sub_categories = parsed_sub
    event.tags = parsed_tags
    event.image_url = saved_image_path

    db.commit()
    return APIResponse(status="success", message="Event updated successfully!")

# 5.4 DELETE EVENT
@router.delete("/events/{event_id}", response_model=APIResponse[None])
async def delete_event(event_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    event = db.query(PlatformItem).filter(PlatformItem.id == event_id, PlatformItem.item_type == "event").first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    db.delete(event)
    db.commit()
    return APIResponse(status="success", message="Event deleted successfully")


# 5.5 BLOCK EVENT (Modal Action)
@router.patch("/events/{event_id}/block", response_model=APIResponse[None])
async def block_event(event_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    event = db.query(PlatformItem).filter(PlatformItem.id == event_id, PlatformItem.item_type == "event").first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    event.status = "blocked"
    db.commit()
    return APIResponse(status="success", message="Event blocked successfully")

"""6. GIFT MANAGEMENT
This section includes all endpoints related to managing gifts, including listing gifts with pagination, search, and creator type filtering, viewing detailed gift modals, creating new gifts with form-data and file upload, and deleting gifts. These endpoints are designed to support the full lifecycle of gift management from the admin dashboard."""

# 6.1 GET ALL GIFTS (Paginated + Searchable + Filter by Creator Type)
@router.get("/gifts", response_model=APIResponse[dict])
async def get_gifts_paginated(
    api_request: Request,
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    creator_type: Optional[str] = "all", # Filter by "Admin", "User", "Provider"
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    query = db.query(PlatformItem).filter(PlatformItem.item_type == "gift")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    if creator_type and creator_type != "all":
        if creator_type.lower() == "admin":
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.is_admin == True)
        else:
            query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    gifts = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    gift_list = []
    for gift in gifts:
        creator_label = resolve_creator_label(gift.creator)
            
        gift_list.append(GiftListItem(
            id=gift.id,
            name=gift.name,
            image_url=get_full_url(api_request, gift.image_url) if gift.image_url else None,
            created_by=creator_label,
            category=gift.category.name if gift.category else "Uncategorized",
            location=gift.location or "N/A",
            fee=gift.price or 0.0
        ))
        
    return APIResponse(
        status="success", 
        message="Gifts fetched", 
        data={"total": total_count, "page": page, "limit": limit, "items": gift_list}
    )

# 6.0 ADMIN AI FLYER PARSING FOR GIFTS
@router.post("/ai/parse-flyer/gift", response_model=APIResponse[GiftAIFlyerExtractionResponse])
async def admin_ai_parse_gift_flyer(
    flyer_image: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    data = await _parse_flyer_image(flyer_image, "gift")
    gift_data = GiftAIFlyerExtractionResponse(**data.dict())
    return APIResponse(status="success", message="Gift flyer parsed successfully", data=gift_data)

# get all gifts without pagination
@router.get("/gifts/all", response_model=APIResponse[List[GiftListItem]])
async def get_all_gifts(
    api_request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a list of all gifts without pagination.
    """
    gifts = db.query(PlatformItem).filter(PlatformItem.item_type == "gift").order_by(PlatformItem.created_at.desc()).all()
    
    gift_list = []
    for gift in gifts:
        creator_label = resolve_creator_label(gift.creator)
            
        gift_list.append(GiftListItem(
            id=gift.id,
            name=gift.name,
            image_url=get_full_url(api_request, gift.image_url) if gift.image_url else None,
            created_by=creator_label,
            category=gift.category.name if gift.category else "Uncategorized",
            location=gift.location or "N/A",
            fee=gift.price or 0.0
        ))
        
    return APIResponse(status="success", message="All gifts fetched", data=gift_list)


# 6.2 VIEW GIFT DETAILS 
@router.get("/gifts/{gift_id}", response_model=APIResponse[GiftDetailResponse])
async def get_gift_detail(
    api_request: Request,
    gift_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    gift = db.query(PlatformItem).filter(
        PlatformItem.id == gift_id, 
        PlatformItem.item_type == "gift"
    ).first()
    
    if not gift:
        raise HTTPException(status_code=404, detail="Gift not found")
        
    creator_label = resolve_creator_label(gift.creator)

    # Combine start and end time into one string if time exists
    time_str = "N/A"
    if gift.start_time:
        time_str = gift.start_time.strftime("%I:%M %p")

    parsed_sub_categories = gift.sub_categories if isinstance(gift.sub_categories, list) else []
    parsed_tags = gift.tags if isinstance(gift.tags, list) else []
    
    # Mock data to support the specific "Includes" section in Image 3
    mock_includes = ["1 class", "Materials for the message", "Duration: 2 Hours"]

    detail = GiftDetailResponse(
        id=gift.id,
        name=gift.name,
        image_url=get_full_url(api_request, gift.image_url) if gift.image_url else None,
        description=gift.description,
        website=gift.website or "www.familyside.com",
        location=gift.location,
        created_by=creator_label,
        status=gift.status.capitalize(),
        date_added=gift.created_at.strftime("%d %b %Y") if gift.created_at else "N/A",
        whatsapp=gift.whatsapp,
        category=gift.category.name if gift.category else "Uncategorized",
        category_id=gift.category_id,
        sub_categories=parsed_sub_categories,
        sub_category_ids=[s.get("id") for s in parsed_sub_categories if isinstance(s, dict) and s.get("id") is not None],
        tags=parsed_tags,
        tag_ids=[t.get("id") for t in parsed_tags if isinstance(t, dict) and t.get("id") is not None],
        date=gift.date.strftime("%d %b %Y") if gift.date else "N/A",
        price=gift.price or 0.0,
        time=time_str,
        includes=mock_includes
    )
    
    return APIResponse(status="success", message="Gift details fetched", data=detail)


# 6.3 CREATE GIFT
@router.post("/gifts", response_model=APIResponse[None])
async def create_gift(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    
    website: Optional[str] = Form(None), # Website isn't in form UI but modal needs it
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    
    date: Optional[str] = Form(None),    # Format: "dd/mm/yyyy"
    
    sub_categories: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # 1. Handle File Upload or Plain Text URL
    form = await request.form()
    upload_file = form.get("photo") or form.get("image_url")
    saved_image_path = None
    if upload_file is not None:
        if hasattr(upload_file, "filename") and upload_file.filename:
            UPLOAD_DIR = "uploads/gifts"
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            file_extension = upload_file.filename.split(".")[-1]
            file_path = os.path.join(UPLOAD_DIR, f"gift_{datetime.utcnow().timestamp()}.{file_extension}")
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_image_path = f"/{file_path}".replace("\\", "/")
        else:
            saved_image_path = str(upload_file).strip() or None

    # 2. Parse JSON lists (Sub-categories and Tags)
    parsed_sub = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)

    # 3. Parse Date Safely
    parsed_date = None
    if date:
        try: parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
        except: 
            try: parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            except: pass

    # 4. Save to Database
    new_gift = PlatformItem(
        item_type="gift",
        name=name,
        location=location,
        category_id=category_id,
        price=price,
        description=description,
        website=website,
        whatsapp=whatsapp,
        email=email,
        instagram=instagram,
        date=parsed_date,
        sub_categories=parsed_sub,
        tags=parsed_tags,
        image_url=saved_image_path,
        creator_id=admin.id,
        status="approved" # Auto-approved
    )
    
    db.add(new_gift)
    db.commit()
    try:
        db.refresh(new_gift)
    except Exception:
        pass
    
    return APIResponse(status="success", message="Gift created successfully!")

@router.put("/gifts/{gift_id}", response_model=APIResponse[None])
async def update_gift(
    request: Request,
    gift_id: int,
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    date: Optional[str] = Form(None),
    sub_categories: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    gift = db.query(PlatformItem).filter(PlatformItem.id == gift_id, PlatformItem.item_type == "gift").first()
    if not gift:
        raise HTTPException(status_code=404, detail="Gift not found")

    form = await request.form()
    upload_file = form.get("photo") or form.get("image_url")
    saved_image_path = gift.image_url
    if upload_file is not None:
        if hasattr(upload_file, "filename") and upload_file.filename:
            UPLOAD_DIR = "uploads/gifts"
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            file_extension = upload_file.filename.split(".")[-1]
            file_name = f"gift_{datetime.utcnow().timestamp()}.{file_extension}"
            file_path = os.path.join(UPLOAD_DIR, file_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_image_path = f"/{file_path}".replace("\\", "/")
        else:
            text_url = str(upload_file).strip()
            saved_image_path = text_url or gift.image_url

    parsed_sub = parse_list_field(sub_categories)
    parsed_tags = parse_list_field(tags)

    parsed_date = None
    if date:
        try:
            parsed_date = datetime.strptime(date, "%d/%m/%Y").date()
        except:
            try:
                parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
            except:
                parsed_date = None

    gift.name = name
    gift.location = location
    gift.category_id = category_id
    gift.price = price
    gift.description = description
    gift.website = website
    gift.whatsapp = whatsapp
    gift.email = email
    gift.instagram = instagram
    gift.date = parsed_date
    gift.sub_categories = parsed_sub
    gift.tags = parsed_tags
    gift.image_url = saved_image_path

    db.commit()
    return APIResponse(status="success", message="Gift updated successfully!")

# 6.4 DELETE GIFT
@router.delete("/gifts/{gift_id}", response_model=APIResponse[None])
async def delete_gift(gift_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    gift = db.query(PlatformItem).filter(PlatformItem.id == gift_id, PlatformItem.item_type == "gift").first()
    if not gift:
        raise HTTPException(status_code=404, detail="Gift not found")
        
    db.delete(gift)
    db.commit()
    return APIResponse(status="success", message="Gift deleted successfully")

# 6.5 BLOCK GIFT (Modal Action)
@router.patch("/gifts/{gift_id}/block", response_model=APIResponse[None])
async def block_gift(gift_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    gift = db.query(PlatformItem).filter(PlatformItem.id == gift_id, PlatformItem.item_type == "gift").first()
    if not gift:
        raise HTTPException(status_code=404, detail="Gift not found")
        
    gift.status = "blocked"
    db.commit()
    return APIResponse(status="success", message="Gift blocked successfully")


# 6.6 CARD DESIGN MANAGEMENT
@router.post("/gift-card-designs", response_model=APIResponse[None])
async def create_gift_card_design(
    request: Request,
    image_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    form = await request.form()
    upload_file = form.get("image") or form.get("image_file") or image_file
    occasion = (form.get("occasion") or form.get("occasion_name") or "").strip() or None
    if not upload_file:
        raise HTTPException(status_code=400, detail="Card design image is required")

    if hasattr(upload_file, "filename") and upload_file.filename:
        UPLOAD_DIR = "uploads/gift_card_designs"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_extension = upload_file.filename.split(".")[-1]
        file_path = os.path.join(UPLOAD_DIR, f"gift_card_design_{datetime.utcnow().timestamp()}.{file_extension}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        saved_image_path = f"/{file_path}".replace("\\", "/")
    else:
        text_url = str(upload_file).strip()
        if not text_url:
            raise HTTPException(status_code=400, detail="Card design image is required")
        saved_image_path = text_url

    design = GiftCardDesign(
        image_url=saved_image_path,
        is_active=True,
        occasion=occasion,
        creator_id=admin.id
    )
    db.add(design)
    db.commit()
    return APIResponse(status="success", message="Gift card design created successfully")

@router.get("/gift-card-designs", response_model=APIResponse[dict])
async def get_gift_card_designs(
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    occasion: Optional[str] = None,
    api_request: Request = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    query = db.query(GiftCardDesign)
    if occasion:
        query = query.filter(GiftCardDesign.occasion == occasion)
    total_count = query.count()
    designs = query.order_by(GiftCardDesign.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    data = [GiftCardDesignItem(
        id=d.id,
        image_url=get_full_url(api_request, d.image_url),
        is_active=d.is_active,
        occasion=d.occasion,
        created_at=d.created_at
    ) for d in designs]

    return APIResponse(status="success", message="Gift card designs fetched", data={"total": total_count, "page": page, "limit": limit, "items": data})

@router.get("/gift-card-designs/{design_id}", response_model=APIResponse[GiftCardDesignDetailResponse])
async def get_gift_card_design_detail(
    design_id: int,
    api_request: Request = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    design = db.query(GiftCardDesign).filter(GiftCardDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Gift card design not found")

    return APIResponse(
        status="success",
        message="Gift card design fetched",
        data=GiftCardDesignDetailResponse(
            id=design.id,
            image_url=get_full_url(api_request, design.image_url),
            is_active=design.is_active,
            occasion=design.occasion,
            creator_id=design.creator_id,
            created_at=design.created_at
        )
    )

@router.delete("/gift-card-designs/{design_id}", response_model=APIResponse[None])
async def delete_gift_card_design(design_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    design = db.query(GiftCardDesign).filter(GiftCardDesign.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Gift card design not found")

    db.delete(design)
    db.commit()
    return APIResponse(status="success", message="Gift card design deleted successfully")


"""7. TAXONOMY MANAGEMENT (Categories, Sub-Categories, Tags)
This section includes all endpoints related to managing the platform's taxonomies, including categories, sub-categories, and tags. Each taxonomy type has endpoints for listing with pagination and search, creating new entries, editing existing entries, and toggling active/block status. These endpoints are designed to support the full lifecycle of taxonomy management from the admin dashboard."""

# 7.1 CATEGORY MANAGEMENT
@router.get("/categories", response_model=APIResponse[dict])
async def get_categories(page: int = 1, limit: int = 20, search: Optional[str] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Category)
    if search: query = query.filter(Category.name.ilike(f"%{search}%"))
    
    total = query.count()
    categories = query.order_by(Category.id.desc()).offset((page - 1) * limit).limit(limit).all()
    DEFAULT_CATEGORY_IMAGE = "uploads/defaults/default_activity.png"
    items = [TaxonomyResponseItem(
        id=c.id,
        name=c.name,
        is_active=c.is_active,
        image_url=get_full_url(api_request, c.image_url if c.image_url else DEFAULT_CATEGORY_IMAGE),
        icon_url=get_full_url(api_request, c.icon_url) if c.icon_url else None
    ) for c in categories]
    return APIResponse(status="success", message="Categories fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get category without paginations
@router.get("/categories/all", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_all_categories(api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    categories = db.query(Category).all()
    DEFAULT_CATEGORY_IMAGE = "uploads/defaults/default_activity.png"
    items = [TaxonomyResponseItem(
        id=c.id,
        name=c.name,
        is_active=c.is_active,
        image_url=get_full_url(api_request, c.image_url if c.image_url else DEFAULT_CATEGORY_IMAGE),
        icon_url=get_full_url(api_request, c.icon_url) if c.icon_url else None
    ) for c in categories]
    return APIResponse(status="success", message="Categories fetched", data=items)

@router.post("/categories", response_model=APIResponse[None])
async def create_category(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    image = form.get("image")
    icon = form.get("icon")

    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")

    if db.query(Category).filter(Category.name.ilike(name)).first():
        raise HTTPException(status_code=400, detail="Category already exists")
    
    image_url = None
    icon_url = None

    upload_dir = "uploads/categories"
    os.makedirs(upload_dir, exist_ok=True)

    if image:
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        image_url = image_path.replace("\\", "/")

    if icon:
        icon_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{icon.filename}")
        with open(icon_path, "wb") as f:
            f.write(await icon.read())
        icon_url = icon_path.replace("\\", "/")

    category = Category(name=name, image_url=image_url, icon_url=icon_url)
    db.add(category)
    db.commit()
    return APIResponse(status="success", message="Category created successfully")

@router.put("/categories/{cat_id}", response_model=APIResponse[None])
async def edit_category(cat_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    form = await request.form()
    name = form.get("name")
    image = form.get("image")
    icon = form.get("icon")

    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")

    existing = db.query(Category).filter(Category.name.ilike(name), Category.id != cat_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category name is already in use")

    upload_dir = "uploads/categories"
    os.makedirs(upload_dir, exist_ok=True)

    if image:
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        cat.image_url = image_path.replace("\\", "/")

    if icon:
        icon_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{icon.filename}")
        with open(icon_path, "wb") as f:
            f.write(await icon.read())
        cat.icon_url = icon_path.replace("\\", "/")

    cat.name = name
    db.commit()
    return APIResponse(status="success", message="Category updated")

@router.patch("/categories/{cat_id}/toggle", response_model=APIResponse[None])
async def toggle_category_status(cat_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat: raise HTTPException(status_code=404, detail="Category not found")
    cat.is_active = not cat.is_active # Toggles between True and False
    db.commit()
    return APIResponse(status="success", message=f"Category {'activated' if cat.is_active else 'blocked'}")

@router.get("/categories/search", response_model=APIResponse[List[TaxonomyResponseItem]])
async def search_categories(search: str, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    categories = db.query(Category).filter(Category.name.ilike(f"%{search}%")).all()
    DEFAULT_CATEGORY_IMAGE = "uploads/defaults/default_activity.png"
    items = [TaxonomyResponseItem(
        id=c.id,
        name=c.name,
        is_active=c.is_active,
        image_url=get_full_url(api_request, c.image_url if c.image_url else DEFAULT_CATEGORY_IMAGE),
        icon_url=get_full_url(api_request, c.icon_url) if c.icon_url else None
    ) for c in categories]
    return APIResponse(status="success", message="Categories search results", data=items)

# delete category (soft delete by blocking and deactivating all related sub-categories)
@router.delete("/categories/{cat_id}", response_model=APIResponse[None])
async def delete_category(cat_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Soft delete: Block the category and all its sub-categories
    cat.is_active = False
    for sub in cat.sub_categories:
        sub.is_active = False
    
    db.commit()
    return APIResponse(status="success", message="Category and its sub-categories have been blocked successfully")


# 7.2 INTEREST MANAGEMENT
@router.get("/interests", response_model=APIResponse[dict])
async def get_interests(page: int = 1, limit: int = 20, search: Optional[str] = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Interest)
    if search:
        query = query.filter(Interest.name.ilike(f"%{search}%"))

    total = query.count()
    interests = query.order_by(Interest.id.desc()).offset((page - 1) * limit).limit(limit).all()
    items = [InterestResponseItem(id=i.id, name=i.name) for i in interests]
    return APIResponse(status="success", message="Interests fetched", data={"total": total, "page": page, "limit": limit, "items": items})

@router.get("/interests/all", response_model=APIResponse[List[InterestResponseItem]])
async def get_all_interests(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    interests = db.query(Interest).order_by(Interest.name.asc()).all()
    items = [InterestResponseItem(id=i.id, name=i.name) for i in interests]
    return APIResponse(status="success", message="Interests fetched", data=items)

@router.post("/interests", response_model=APIResponse[None])
async def create_interest(payload: InterestRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if db.query(Interest).filter(func.lower(Interest.name) == payload.name.strip().lower()).first():
        raise HTTPException(status_code=400, detail="Interest already exists")

    interest = Interest(name=payload.name.strip())
    db.add(interest)
    db.commit()
    return APIResponse(status="success", message="Interest created successfully")

@router.put("/interests/{interest_id}", response_model=APIResponse[None])
async def edit_interest(interest_id: int, payload: InterestRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    interest = db.query(Interest).filter(Interest.id == interest_id).first()
    if not interest:
        raise HTTPException(status_code=404, detail="Interest not found")

    existing = db.query(Interest).filter(func.lower(Interest.name) == payload.name.strip().lower(), Interest.id != interest_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Another interest with this name already exists")

    interest.name = payload.name.strip()
    db.commit()
    return APIResponse(status="success", message="Interest updated successfully")

@router.delete("/interests/{interest_id}", response_model=APIResponse[None])
async def delete_interest(interest_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    interest = db.query(Interest).filter(Interest.id == interest_id).first()
    if not interest:
        raise HTTPException(status_code=404, detail="Interest not found")

    db.delete(interest)
    db.commit()
    return APIResponse(status="success", message="Interest deleted successfully")


# 7.2 SUB-CATEGORY MANAGEMENT
@router.get("/sub-categories", response_model=APIResponse[dict])
async def get_sub_categories(page: int = 1, limit: int = 20, search: Optional[str] = None, category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(SubCategory)
    if search: query = query.filter(SubCategory.name.ilike(f"%{search}%"))
    if category_id: query = query.filter(SubCategory.category_id == category_id)
    
    total = query.count()
    sub_cats = query.order_by(SubCategory.id.desc()).offset((page - 1) * limit).limit(limit).all()
    DEFAULT_SUBCATEGORY_IMAGE = "uploads/defaults/default_activity.png"
    items = [TaxonomyResponseItem(id=s.id, name=s.name, is_active=s.is_active, image_url=get_full_url(api_request, s.image_url if s.image_url else DEFAULT_SUBCATEGORY_IMAGE), category_id=s.category_id, category_name=s.category.name if s.category else "") for s in sub_cats]
    return APIResponse(status="success", message="Sub-Categories fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get sub-categories based on category_id without paginations
@router.get("/sub-categories/{category_id}", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_sub_categories_by_category(category_id: int, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    sub_cats = db.query(SubCategory).filter(SubCategory.category_id == category_id).all()
    DEFAULT_SUBCATEGORY_IMAGE = "uploads/defaults/default_activity.png"
    return APIResponse(status="success", message="Sub-Categories fetched", data=[TaxonomyResponseItem(id=s.id, name=s.name, is_active=s.is_active, image_url=get_full_url(api_request, s.image_url if s.image_url else DEFAULT_SUBCATEGORY_IMAGE), category_id=s.category_id, category_name=s.category.name if s.category else "") for s in sub_cats])

@router.post("/sub-categories", response_model=APIResponse[None])
async def create_sub_category(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    category_id = form.get("category_id")
    image = form.get("image")
    icon = form.get("icon")
    upload_file = icon or image
    
    if not name or not category_id:
        raise HTTPException(status_code=400, detail="Sub-category name and category_id are required")
    
    if not db.query(Category).filter(Category.id == int(category_id)).first():
        raise HTTPException(status_code=404, detail="Parent Category not found")
    
    image_url = None
    if upload_file:
        # Save image/icon
        upload_dir = "uploads/subcategories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{upload_file.filename}")
        with open(image_path, "wb") as f:
            f.write(await upload_file.read())
        image_url = image_path.replace("\\", "/")
    else:
        image_url = "uploads/defaults/default_activity.png"
    
    db.add(SubCategory(name=name, category_id=int(category_id), image_url=image_url))
    db.commit()
    return APIResponse(status="success", message="Sub-Category created successfully")

@router.put("/sub-categories/{sub_id}", response_model=APIResponse[None])
async def edit_sub_category(sub_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    sub = db.query(SubCategory).filter(SubCategory.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-Category not found")

    form = await request.form()
    name = form.get("name")
    category_id = form.get("category_id")
    image = form.get("image")
    icon = form.get("icon")
    upload_file = icon or image

    if not name or not category_id:
        raise HTTPException(status_code=400, detail="Sub-category name and category_id are required")

    if not db.query(Category).filter(Category.id == int(category_id)).first():
        raise HTTPException(status_code=404, detail="Parent Category not found")

    if upload_file:
        upload_dir = "uploads/subcategories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{upload_file.filename}")
        with open(image_path, "wb") as f:
            f.write(await upload_file.read())
        sub.image_url = image_path.replace("\\", "/")

    sub.name = name
    sub.category_id = int(category_id)
    db.commit()
    return APIResponse(status="success", message="Sub-Category updated")

@router.patch("/sub-categories/{sub_id}/toggle", response_model=APIResponse[None])
async def toggle_sub_category_status(sub_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    sub = db.query(SubCategory).filter(SubCategory.id == sub_id).first()
    if not sub: raise HTTPException(status_code=404, detail="Sub-Category not found")
    sub.is_active = not sub.is_active
    db.commit()
    return APIResponse(status="success", message=f"Sub-Category {'activated' if sub.is_active else 'blocked'}")

@router.get("/sub-categories/search", response_model=APIResponse[List[TaxonomyResponseItem]])
async def search_sub_categories(search: str, category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(SubCategory).filter(SubCategory.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(SubCategory.category_id == category_id)
    sub_cats = query.all()
    items = [TaxonomyResponseItem(id=s.id, name=s.name, is_active=s.is_active, image_url=get_full_url(api_request, s.image_url) if s.image_url else None, category_id=s.category_id, category_name=s.category.name if s.category else "") for s in sub_cats]
    return APIResponse(status="success", message="Sub-Categories search results", data=items)

# delete sub-category
@router.delete("/sub-categories/{sub_id}", response_model=APIResponse[None])
async def delete_sub_category(sub_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    sub = db.query(SubCategory).filter(SubCategory.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-Category not found")
    db.delete(sub)
    db.commit()
    return APIResponse(status="success", message="Sub-Category deleted successfully")

# 7.3 TAG MANAGEMENT
@router.get("/tags", response_model=APIResponse[dict])
async def get_tags(page: int = 1, limit: int = 20, search: Optional[str] = None, category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Tag)
    if search: query = query.filter(Tag.name.ilike(f"%{search}%"))
    if category_id is not None:
        query = query.filter(Tag.category_id == category_id)
    
    total = query.count()
    tags = query.order_by(Tag.id.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = [TaxonomyResponseItem(
        id=t.id,
        name=t.name,
        is_active=t.is_active,
        image_url=get_full_url(api_request, t.image_url) if t.image_url else None,
        category_id=t.category_id,
        category_name=t.category.name if t.category else None
    ) for t in tags]
    return APIResponse(status="success", message="Tags fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get tags without paginations
@router.get("/tags/all", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_all_tags(category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Tag)
    if category_id is not None:
        query = query.filter(Tag.category_id == category_id)
    tags = query.order_by(Tag.id.desc()).all()
    return APIResponse(status="success", message="Tags fetched", data=[TaxonomyResponseItem(
        id=t.id,
        name=t.name,
        is_active=t.is_active,
        image_url=get_full_url(api_request, t.image_url) if t.image_url else None,
        category_id=t.category_id,
        category_name=t.category.name if t.category else None
    ) for t in tags])

@router.post("/tags", response_model=APIResponse[None])
async def create_tag(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    category_id = form.get("category_id")
    image = form.get("image")
    
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")
    
    if category_id:
        if not db.query(Category).filter(Category.id == int(category_id)).first():
            raise HTTPException(status_code=404, detail="Parent Category not found")
    
    existing_query = db.query(Tag).filter(Tag.name.ilike(name))
    if category_id is not None:
        existing_query = existing_query.filter(Tag.category_id == int(category_id))
    else:
        existing_query = existing_query.filter(Tag.category_id == None)
    
    if existing_query.first():
        raise HTTPException(status_code=400, detail="Tag already exists for this category")
    
    image_url = None
    if image:
        # Save image
        upload_dir = "uploads/tags"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        image_url = image_path.replace("\\", "/")
    
    db.add(Tag(name=name, category_id=int(category_id) if category_id else None, image_url=image_url))
    db.commit()
    return APIResponse(status="success", message="Tag created successfully")

@router.put("/tags/{tag_id}", response_model=APIResponse[None])
async def edit_tag(tag_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    form = await request.form()
    name = form.get("name")
    category_id = form.get("category_id")
    image = form.get("image")

    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    if category_id:
        if not db.query(Category).filter(Category.id == int(category_id)).first():
            raise HTTPException(status_code=404, detail="Parent Category not found")

    existing_query = db.query(Tag).filter(Tag.name.ilike(name), Tag.id != tag_id)
    if category_id is not None:
        existing_query = existing_query.filter(Tag.category_id == int(category_id))
    else:
        existing_query = existing_query.filter(Tag.category_id == None)
    if existing_query.first():
        raise HTTPException(status_code=400, detail="Tag already exists for this category")
    
    if image:
        upload_dir = "uploads/tags"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        tag.image_url = image_path.replace("\\", "/")

    tag.name = name
    tag.category_id = int(category_id) if category_id else None
    db.commit()
    return APIResponse(status="success", message="Tag updated")

# search tags
@router.get("/tags/search", response_model=APIResponse[List[TaxonomyResponseItem]])
async def search_tags(search: str, category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Tag).filter(Tag.name.ilike(f"%{search}%"))
    if category_id is not None:
        query = query.filter(Tag.category_id == category_id)
    tags = query.all()
    items = [TaxonomyResponseItem(
        id=t.id,
        name=t.name,
        is_active=t.is_active,
        image_url=get_full_url(api_request, t.image_url) if t.image_url else None,
        category_id=t.category_id,
        category_name=t.category.name if t.category else None
    ) for t in tags]
    return APIResponse(status="success", message="Tags search results", data=items)


"""
8. ADMIN SETTINGS
"""

# 8 ADMIN SETTINGS (Profile & Security)
@router.get("/settings/profile", response_model=APIResponse[AdminProfileResponse])
async def get_admin_profile(
    api_request: Request,
    admin: User = Depends(get_current_admin)
):
    """
    Fetches the admin's current profile data to populate the Settings form.
    """
    detail = AdminProfileResponse(
        name=admin.full_name,
        image_url=get_full_url(api_request, admin.profile_image_url) if admin.profile_image_url else None,
        email=admin.email,
        phone_number=admin.phone_number
    )
    return APIResponse(status="success", message="Profile data fetched", data=detail)


@router.patch("/settings/profile", response_model=APIResponse[AdminProfileResponse])
async def update_admin_profile(
    payload: AdminProfileUpdateRequest, 
    db: Session = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    """
    Updates the Account Information form (Name, Email, Phone).
    """
    # Prevent changing email to one that already exists for another user
    # if payload.email != admin.email:
    #     existing_user = db.query(User).filter(User.email == payload.email).first()
    #     if existing_user:
    #         raise HTTPException(status_code=400, detail="This email is already in use by another account.")
            
    admin.full_name = payload.name
    # admin.email = payload.email
    admin.phone_number = payload.phone_number
    db.commit()
    
    # Return the updated data back to the frontend
    updated_detail = AdminProfileResponse(
        name=admin.full_name,
        # email=admin.email,
        phone_number=admin.phone_number
    )
    return APIResponse(status="success", message="Account information updated successfully", data=updated_detail)

# Only admin profile picture update/change endpoint
@router.patch("/settings/profile/image", response_model=APIResponse[AdminProfileResponse])
async def update_admin_profile_image(
    request: Request,
    db: Session = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    """
    Updates the admin's profile picture.
    """
    form = await request.form()
    image = form.get("image")
    
    if not image:
        raise HTTPException(status_code=400, detail="No image file provided.")
    
    # Save the new profile image
    upload_dir = "uploads/admins"
    os.makedirs(upload_dir, exist_ok=True)
    image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
    
    with open(image_path, "wb") as f:
        f.write(await image.read())
    
    # Update the admin's profile image URL in the database
    admin.profile_image_url = image_path.replace("\\", "/")
    db.commit()
    
    updated_detail = AdminProfileResponse(
        name=admin.full_name,
        image_url=get_full_url(request, admin.profile_image_url) if admin.profile_image_url else None,
        email=admin.email,
        phone_number=admin.phone_number
    )
    
    return APIResponse(status="success", message="Profile picture updated successfully", data=updated_detail)


@router.patch("/settings/security", response_model=APIResponse[None])
async def update_admin_password(
    payload: ChangePasswordRequest, 
    db: Session = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    """
    Updates the Security form (Password change).
    Note: The frontend should verify 'New Password' and 'Confirm New Password' 
    match before sending this request to the backend.
    """
    # 1. Verify that the current password provided is correct
    if not verify_password(payload.current_password, admin.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    # 2. Prevent reusing the same password
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password cannot be the same as the current password")
    
    # 3. Hash and save the new password
    admin.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    
    return APIResponse(status="success", message="Security password updated successfully")

@router.get("/support/tickets", response_model=APIResponse[dict])
async def list_support_tickets(
    page: int = 1, 
    limit: int = 10, 
    db: Session = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    """Allows Admin to see all user problems submitted via the app"""
    query = db.query(SupportMessage)
    total = query.count()
    tickets = query.order_by(SupportMessage.created_at.desc()).offset((page-1)*limit).limit(limit).all()
    
    return APIResponse(
        status="success", 
        message="Support tickets fetched", 
        data={"total": total, "items": tickets}
    )

@router.patch("/support/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Marks a problem as fixed/resolved"""
    ticket = db.query(SupportMessage).filter(SupportMessage.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.status = "resolved"
    db.commit()
    return {"message": "Ticket marked as resolved"}

@router.get("/legal/{doc_type}", response_model=APIResponse[LegalDocumentResponse])
async def get_legal_document_admin(doc_type: str, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Allows admin to see the current text of a policy"""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == doc_type).first()
    if not doc:
        # Return empty if not created yet
        return APIResponse(
            status="success",
            message="Document not found",
            data={"document_type": doc_type, "content": "", "updated_at": None}
        )
    
    return APIResponse(status="success", message="Document fetched", data=doc)

@router.get("/legal/privacy-policy", response_model=APIResponse[LegalDocumentResponse])
async def get_privacy_policy_admin(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Fetches the Privacy Policy content for admin management"""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == "privacy_policy").first()
    if not doc:
        return APIResponse(
            status="success",
            message="Document not found",
            data={"document_type": "privacy_policy", "content": "", "updated_at": None}
        )
    return APIResponse(status="success", message="Privacy Policy fetched", data=doc)

@router.get("/legal/terms-and-conditions", response_model=APIResponse[LegalDocumentResponse])
async def get_terms_and_conditions_admin(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Fetches the Terms and Conditions content for admin management"""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == "terms_and_conditions").first()
    if not doc:
        return APIResponse(
            status="success",
            message="Document not found",
            data={"document_type": "terms_and_conditions", "content": "", "updated_at": None}
        )
    return APIResponse(status="success", message="Terms and Conditions fetched", data=doc)

@router.put("/legal/{doc_type}", response_model=APIResponse[None])
async def update_legal_document(doc_type: str, payload: LegalDocumentRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Allows admin to Create or Update the Privacy Policy"""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == doc_type).first()
    
    if doc:
        doc.content = payload.content
    else:
        new_doc = LegalDocument(document_type=doc_type, content=payload.content)
        db.add(new_doc)
    
    db.commit()
    return APIResponse(status="success", message=f"{doc_type.replace('_', ' ').capitalize()} updated successfully")

@router.put("/legal/privacy-policy", response_model=APIResponse[None])
async def update_privacy_policy_admin(payload: LegalDocumentRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Creates or updates the Privacy Policy."""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == "privacy_policy").first()
    if doc:
        doc.content = payload.content
    else:
        db.add(LegalDocument(document_type="privacy_policy", content=payload.content))
    db.commit()
    return APIResponse(status="success", message="Privacy Policy updated successfully")

@router.put("/legal/terms-and-conditions", response_model=APIResponse[None])
async def update_terms_and_conditions_admin(payload: LegalDocumentRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Creates or updates the Terms and Conditions."""
    doc = db.query(LegalDocument).filter(LegalDocument.document_type == "terms_and_conditions").first()
    if doc:
        doc.content = payload.content
    else:
        db.add(LegalDocument(document_type="terms_and_conditions", content=payload.content))
    db.commit()
    return APIResponse(status="success", message="Terms and Conditions updated successfully")