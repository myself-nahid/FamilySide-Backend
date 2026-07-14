from alembic.environment import Optional
from alembic.util import status
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.api.deps import get_db, get_current_admin
from app.core.utils import get_full_url
from app.models.user import User, Child
from app.models.core_data import PlatformItem, Category, SupportMessage
from app.schemas.auth_schema import APIResponse, ChangePasswordRequest
from datetime import datetime, timedelta
from sqlalchemy import func, and_
import pandas as pd
from io import BytesIO
import os
import shutil
import json
from app.schemas.admin_schema import (
    DashboardOverviewResponse, TrendMetric, StatusDistribution,
    FlaggedItemListItem, PendingApprovalListItem, UpcomingEventListItem,
    ChartDataResponse, ChartDataPoint
)
from app.schemas.admin_schema import (
    DashboardStatsResponse, UserActionRequest, 
    ItemStatusUpdateRequest, CreateItemRequest, AdminProfileUpdateRequest, UserDetailResponse, ChildResponse, NotificationItem, ItemReviewDetailResponse, UserDetailResponse, ActivityListItem, ActivityDetailResponse, CreateActivityRequest, EventListItem, EventDetailResponse, GiftListItem, GiftDetailResponse, AdminProfileResponse
)
from app.models.core_data import Category, SubCategory, Tag
from app.schemas.admin_schema import TaxonomyRequest, SubCategoryRequest, TaxonomyResponseItem
from app.models.core_data import Notification
from app.core.security import get_password_hash, verify_password
from typing import List

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

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
        query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    activities = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    activity_list = []
    for activity in activities:
        creator_label = "Admin"
        if activity.creator:
            creator_label = activity.creator.user_type.capitalize() if activity.creator.user_type else "User"
            
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
        creator_label = "Admin"
        if activity.creator:
            creator_label = activity.creator.user_type.capitalize() if activity.creator.user_type else "User"
            
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
        
    creator_label = "Admin"
    if activity.creator:
        creator_label = activity.creator.user_type.capitalize() if activity.creator.user_type else "User"

    # Mock tags for MVP display purposes
    mock_tags = ["Education", "Indoor", "Paid"]

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
        opening_days=activity.opening_days,
        opening_hours=activity.opening_hours,
        tags=mock_tags
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
    parsed_sub_categories = []
    parsed_tags = []
    if sub_categories:
        try: parsed_sub_categories = json.loads(sub_categories)
        except: parsed_sub_categories = [sub_categories] # Fallback if standard string
        
    if tags:
        try: parsed_tags = json.loads(tags)
        except: parsed_tags = [tags]

    # 3. Save to Database
    new_activity = PlatformItem(
        item_type="activity",
        name=name,
        location=location,
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

@router.post("/activities/bulk-upload", response_model=APIResponse[dict])
async def bulk_upload_activities(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Accepts an Excel (.xlsx) file and creates multiple activities.
    Ensures data validation and handles comma-separated tags/sub-categories.
    """
    # 1. Validate File Extension
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    try:
        # 2. Read Excel file using Pandas
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        
        # Replace NaN (empty Excel cells) with None for Python compatibility
        df = df.where(pd.notnull(df), None)

        success_count = 0
        errors = []

        # 3. Iterate through rows
        for index, row in df.iterrows():
            try:
                # Validation: Ensure Category exists
                cat_id = int(row['category_id'])
                category = db.query(Category).filter(Category.id == cat_id).first()
                if not category:
                    errors.append(f"Row {index+2}: Category ID {cat_id} not found.")
                    continue

                # Process comma-separated tags/sub-categories into JSON lists
                def format_list(val):
                    if not val: return []
                    return [item.strip() for item in str(val).split(',')]

                new_activity = PlatformItem(
                    item_type="activity",
                    name=str(row['name']),
                    description=str(row['description']),
                    category_id=cat_id,
                    location=str(row['location']),
                    lat=float(row['lat']) if row['lat'] else None,
                    lng=float(row['lng']) if row['lng'] else None,
                    price=float(row['price']) if row['price'] else 0.0,
                    website=row['website'],
                    whatsapp=str(row['whatsapp']) if row['whatsapp'] else None,
                    email=row['email'],
                    instagram=row['instagram'],
                    opening_days=row['opening_days'],
                    opening_hours=row['opening_hours'],
                    sub_categories=format_list(row['sub_categories']),
                    tags=format_list(row['tags']),
                    creator_id=admin.id,
                    status="approved" # Admin bulk uploads are auto-approved
                )
                db.add(new_activity)
                success_count += 1

            except Exception as e:
                errors.append(f"Row {index+2}: Internal error - {str(e)}")

        db.commit()

        return APIResponse(
            status="success", 
            message=f"Import complete. {success_count} activities added.",
            data={"success_count": success_count, "errors": errors}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

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
        query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    events = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    event_list = []
    for event in events:
        creator_label = "Admin"
        if event.creator:
            creator_label = event.creator.user_type.capitalize() if event.creator.user_type else "User"
            
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
        creator_label = "Admin"
        if event.creator:
            creator_label = event.creator.user_type.capitalize() if event.creator.user_type else "User"
            
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
        
    creator_label = "Admin"
    if event.creator:
        creator_label = event.creator.user_type.capitalize() if event.creator.user_type else "User"

    # Combine start and end time into one readable string
    time_str = "N/A"
    if event.start_time:
        time_str = event.start_time.strftime("%I:%M %p")
        if event.end_time:
            time_str += f" to {event.end_time.strftime('%I:%M %p')}"

    # Safely parse JSON tags
    tags = event.tags if isinstance(event.tags, list) else []

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
        date=event.date.strftime("%d %b %Y") if event.date else "N/A",
        time=time_str,
        tags=tags
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
    parsed_sub = []
    parsed_tags = []
    
    if sub_categories:
        try: 
            parsed_sub = json.loads(sub_categories)
        except: 
            parsed_sub = [sub_categories]
            
    if tags:
        try: 
            parsed_tags = json.loads(tags)
        except: 
            parsed_tags = [tags]


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
        query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    gifts = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    gift_list = []
    for gift in gifts:
        creator_label = "Admin"
        if gift.creator:
            creator_label = gift.creator.user_type.capitalize() if gift.creator.user_type else "User"
            
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
        creator_label = "Admin"
        if gift.creator:
            creator_label = gift.creator.user_type.capitalize() if gift.creator.user_type else "User"
            
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
        
    creator_label = "Admin"
    if gift.creator:
        creator_label = gift.creator.user_type.capitalize() if gift.creator.user_type else "User"

    # Combine start and end time into one string if time exists
    time_str = "N/A"
    if gift.start_time:
        time_str = gift.start_time.strftime("%I:%M %p")

    tags = gift.tags if isinstance(gift.tags, list) else []
    
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
        date=gift.date.strftime("%d %b %Y") if gift.date else "N/A",
        time=time_str,
        tags=tags,
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
    import json
    parsed_sub = []
    parsed_tags = []
    if sub_categories:
        try: parsed_sub = json.loads(sub_categories)
        except: parsed_sub = [sub_categories]
    if tags:
        try: parsed_tags = json.loads(tags)
        except: parsed_tags = [tags]

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


"""7. TAXONOMY MANAGEMENT (Categories, Sub-Categories, Tags)
This section includes all endpoints related to managing the platform's taxonomies, including categories, sub-categories, and tags. Each taxonomy type has endpoints for listing with pagination and search, creating new entries, editing existing entries, and toggling active/block status. These endpoints are designed to support the full lifecycle of taxonomy management from the admin dashboard."""

# 7.1 CATEGORY MANAGEMENT
@router.get("/categories", response_model=APIResponse[dict])
async def get_categories(page: int = 1, limit: int = 20, search: Optional[str] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Category)
    if search: query = query.filter(Category.name.ilike(f"%{search}%"))
    
    total = query.count()
    categories = query.order_by(Category.id.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = [TaxonomyResponseItem(id=c.id, name=c.name, is_active=c.is_active, image_url=get_full_url(api_request, c.image_url) if c.image_url else None) for c in categories]
    return APIResponse(status="success", message="Categories fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get category without paginations
@router.get("/categories/all", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_all_categories(api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    categories = db.query(Category).all()
    items = [TaxonomyResponseItem(id=c.id, name=c.name, is_active=c.is_active, image_url=get_full_url(api_request, c.image_url) if c.image_url else None) for c in categories]
    return APIResponse(status="success", message="Categories fetched", data=items)

@router.post("/categories", response_model=APIResponse[None])
async def create_category(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    image = form.get("image")
    
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    
    if db.query(Category).filter(Category.name.ilike(name)).first():
        raise HTTPException(status_code=400, detail="Category already exists")
    
    image_url = None
    if image:
        # Save image
        upload_dir = "uploads/categories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        image_url = image_path.replace("\\", "/")
    
    db.add(Category(name=name, image_url=image_url))
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

    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")

    existing = db.query(Category).filter(Category.name.ilike(name), Category.id != cat_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category name is already in use")

    if image:
        upload_dir = "uploads/categories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        cat.image_url = image_path.replace("\\", "/")

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
    items = [TaxonomyResponseItem(id=c.id, name=c.name, is_active=c.is_active, image_url=get_full_url(api_request, c.image_url) if c.image_url else None) for c in categories]
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


# 7.2 SUB-CATEGORY MANAGEMENT
@router.get("/sub-categories", response_model=APIResponse[dict])
async def get_sub_categories(page: int = 1, limit: int = 20, search: Optional[str] = None, category_id: Optional[int] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(SubCategory)
    if search: query = query.filter(SubCategory.name.ilike(f"%{search}%"))
    if category_id: query = query.filter(SubCategory.category_id == category_id)
    
    total = query.count()
    sub_cats = query.order_by(SubCategory.id.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = [TaxonomyResponseItem(id=s.id, name=s.name, is_active=s.is_active, image_url=get_full_url(api_request, s.image_url) if s.image_url else None, category_id=s.category_id, category_name=s.category.name if s.category else "") for s in sub_cats]
    return APIResponse(status="success", message="Sub-Categories fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get sub-categories based on category_id without paginations
@router.get("/sub-categories/{category_id}", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_sub_categories_by_category(category_id: int, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    sub_cats = db.query(SubCategory).filter(SubCategory.category_id == category_id).all()
    return APIResponse(status="success", message="Sub-Categories fetched", data=[TaxonomyResponseItem(id=s.id, name=s.name, is_active=s.is_active, image_url=get_full_url(api_request, s.image_url) if s.image_url else None, category_id=s.category_id, category_name=s.category.name if s.category else "") for s in sub_cats])

@router.post("/sub-categories", response_model=APIResponse[None])
async def create_sub_category(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    category_id = form.get("category_id")
    image = form.get("image")
    
    if not name or not category_id:
        raise HTTPException(status_code=400, detail="Sub-category name and category_id are required")
    
    if not db.query(Category).filter(Category.id == int(category_id)).first():
        raise HTTPException(status_code=404, detail="Parent Category not found")
    
    image_url = None
    if image:
        # Save image
        upload_dir = "uploads/subcategories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        image_url = image_path.replace("\\", "/")
    
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

    if not name or not category_id:
        raise HTTPException(status_code=400, detail="Sub-category name and category_id are required")

    if not db.query(Category).filter(Category.id == int(category_id)).first():
        raise HTTPException(status_code=404, detail="Parent Category not found")

    if image:
        upload_dir = "uploads/subcategories"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
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
async def get_tags(page: int = 1, limit: int = 20, search: Optional[str] = None, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(Tag)
    if search: query = query.filter(Tag.name.ilike(f"%{search}%"))
    
    total = query.count()
    tags = query.order_by(Tag.id.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = [TaxonomyResponseItem(id=t.id, name=t.name, is_active=t.is_active, image_url=get_full_url(api_request, t.image_url) if t.image_url else None) for t in tags]
    return APIResponse(status="success", message="Tags fetched", data={"total": total, "page": page, "limit": limit, "items": items})

# get tags without paginations
@router.get("/tags/all", response_model=APIResponse[List[TaxonomyResponseItem]])
async def get_all_tags(api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tags = db.query(Tag).all()
    return APIResponse(status="success", message="Tags fetched", data=[TaxonomyResponseItem(id=t.id, name=t.name, is_active=t.is_active, image_url=get_full_url(api_request, t.image_url) if t.image_url else None) for t in tags])

@router.post("/tags", response_model=APIResponse[None])
async def create_tag(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    form = await request.form()
    name = form.get("name")
    image = form.get("image")
    
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")
    
    if db.query(Tag).filter(Tag.name.ilike(name)).first():
        raise HTTPException(status_code=400, detail="Tag already exists")
    
    image_url = None
    if image:
        # Save image
        upload_dir = "uploads/tags"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        image_url = image_path.replace("\\", "/")
    
    db.add(Tag(name=name, image_url=image_url))
    db.commit()
    return APIResponse(status="success", message="Tag created successfully")

@router.put("/tags/{tag_id}", response_model=APIResponse[None])
async def edit_tag(tag_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    form = await request.form()
    name = form.get("name")
    image = form.get("image")

    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    existing = db.query(Tag).filter(Tag.name.ilike(name), Tag.id != tag_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tag name is already in use")

    if image:
        upload_dir = "uploads/tags"
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(upload_dir, f"{datetime.utcnow().timestamp()}_{image.filename}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        tag.image_url = image_path.replace("\\", "/")

    tag.name = name
    db.commit()
    return APIResponse(status="success", message="Tag updated")

@router.patch("/tags/{tag_id}/toggle", response_model=APIResponse[None])
async def toggle_tag_status(tag_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag: raise HTTPException(status_code=404, detail="Tag not found")
    tag.is_active = not tag.is_active
    db.commit()
    return APIResponse(status="success", message=f"Tag {'activated' if tag.is_active else 'blocked'}")

# search tags
@router.get("/tags/search", response_model=APIResponse[List[TaxonomyResponseItem]])
async def search_tags(search: str, api_request: Request = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    tags = db.query(Tag).filter(Tag.name.ilike(f"%{search}%")).all()
    items = [TaxonomyResponseItem(id=t.id, name=t.name, is_active=t.is_active, image_url=get_full_url(api_request, t.image_url) if t.image_url else None) for t in tags]
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